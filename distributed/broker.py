"""One durable ingest queue with persistent receipts scoped to each worker."""
import json
import logging
import time
from decimal import InvalidOperation

import pika
import psutil

from worker.models import utc_now

LOG = logging.getLogger(__name__)
QUEUE = "linuxck.v1.ingest"
DEAD = QUEUE + ".dead"


def connect(address):
    settings = pika.URLParameters(address)
    settings.socket_timeout = 3
    settings.stack_timeout = 5
    settings.blocked_connection_timeout = 5
    settings.heartbeat = 15
    settings.connection_attempts = 1
    return pika.BlockingConnection(settings)


def topology(channel):
    channel.queue_declare(DEAD, durable=True)
    channel.queue_declare(QUEUE, durable=True, arguments={
        "x-dead-letter-exchange": "", "x-dead-letter-routing-key": DEAD,
    })
    channel.confirm_delivery()


def emit(channel, queue, body, *, durable=True, ttl=None):
    channel.basic_publish("", queue, json.dumps(body, allow_nan=False), mandatory=True,
                          properties=pika.BasicProperties(content_type="application/json",
                                                          message_id=body.get("id"), expiration=ttl,
                                                          delivery_mode=2 if durable else 1))


def publisher(address, local, worker_id, stop, health):
    receipts = "linuxck.v1.receipt." + worker_id
    delay = 1
    down_since = time.monotonic()
    last_master_contact = down_since
    metrics = psutil.Process()
    metrics.cpu_percent()
    while not stop.is_set():
        connection = None
        try:
            connection = connect(address)
            channel = connection.channel()
            topology(channel)
            channel.queue_declare(receipts, durable=True)
            last_publish = {}
            next_heartbeat = 0.0
            while not stop.is_set():
                connection.process_data_events(time_limit=0)
                method, _, payload = channel.basic_get(receipts)
                while method is not None:
                    ack = json.loads(payload)
                    if ack.get("version") == 1 and ack.get("worker_id") == worker_id:
                        if ack.get("committed") is True:
                            local.receipt(ack["id"])
                            last_master_contact = time.monotonic()
                        elif ack.get("type") == "heartbeat_receipt":
                            last_master_contact = time.monotonic()
                    channel.basic_ack(method.delivery_tag)
                    method, _, payload = channel.basic_get(receipts)
                now = time.monotonic()
                if now >= next_heartbeat:
                    net = psutil.net_io_counters()
                    emit(channel, QUEUE, dict(type="heartbeat", at=utc_now(), worker_id=worker_id,
                         exchange=local.exchange, stats={**local.status(), **health,
                         "broker_outage_seconds": round(now - down_since, 2) if down_since else 0,
                         "master_contact_age_seconds": round(max(0, now - last_master_contact), 2),
                         "cpu_percent": metrics.cpu_percent(),
                         "rss_mib": round(metrics.memory_info().rss / 2**20, 2),
                         "disk_percent": psutil.disk_usage(str(local.path.parent)).percent,
                         "network_rx_bytes": net.bytes_recv, "network_tx_bytes": net.bytes_sent}),
                         durable=False, ttl="10000")
                    next_heartbeat = now + 5
                    down_since = None
                    delay = 1
                last_publish = {key: sent for key, sent in last_publish.items() if now - sent < 15}
                for key, encoded in local.pending():
                    if stop.is_set():
                        break
                    if key not in last_publish:
                        emit(channel, QUEUE, json.loads(encoded))
                        last_publish[key] = now
                stop.wait(0.5)
        except Exception as error:
            if down_since is None:
                down_since = time.monotonic()
            LOG.warning("Publisher unavailable (%s); SQLite outbox retained", type(error).__name__)
        finally:
            if connection and connection.is_open:
                try:
                    connection.close()
                except pika.exceptions.AMQPError:
                    pass
        if not stop.is_set():
            stop.wait(delay)
            delay = min(delay * 2, 15)


def consumer(address, postgres, stop):
    delay = 1
    while not stop.is_set():
        connection = None
        try:
            connection = connect(address)
            channel = connection.channel()
            topology(channel)
            while not stop.is_set():
                method, _, payload = channel.basic_get(QUEUE)
                if method is None:
                    connection.process_data_events(time_limit=0.4)
                    delay = 1
                    continue
                try:
                    body = json.loads(payload)
                    if body.get("type") == "heartbeat":
                        postgres.heartbeat(body)
                        queue = "linuxck.v1.receipt." + body["worker_id"]
                        channel.queue_declare(queue, durable=True)
                        emit(channel, queue, dict(version=1, type="heartbeat_receipt",
                                                  worker_id=body["worker_id"]),
                             durable=False, ttl="10000")
                    else:
                        key = postgres.ingest(body)
                        queue = "linuxck.v1.receipt." + body["worker_id"]
                        channel.queue_declare(queue, durable=True)
                        emit(channel, queue, dict(version=1, id=key, worker_id=body["worker_id"], committed=True))
                except (ValueError, KeyError, TypeError, AttributeError, InvalidOperation) as error:
                    channel.basic_reject(method.delivery_tag, requeue=False)
                    LOG.warning("Invalid delivery sent to DLQ (%s)", type(error).__name__)
                    continue
                # On PostgreSQL or broker failure, closing the channel requeues the unacknowledged delivery.
                channel.basic_ack(method.delivery_tag)
                delay = 1
        except Exception as error:
            LOG.warning("Consumer unavailable (%s); unacknowledged deliveries retained", type(error).__name__)
        finally:
            if connection and connection.is_open:
                try:
                    connection.close()
                except pika.exceptions.AMQPError:
                    pass
        if not stop.is_set():
            stop.wait(delay)
            delay = min(delay * 2, 15)
