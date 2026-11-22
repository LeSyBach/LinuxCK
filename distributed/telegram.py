import os
import time
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import httpx

from .protocol import utc

TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def display(value):
    return value.astimezone(TZ).strftime("%d/%m/%Y %H:%M:%S") + " (UTC+7)"


def preview(report, now, kind="report", threshold=None):
    lines = [f"{'CẢNH BÁO CHÊNH LỆCH' if kind == 'spread' else 'BÁO CÁO GIÁ'} {report['symbol']}",
             f"Cửa sổ: {display(utc(report['start']))} → {display(utc(report['end']))}"]
    for exchange, item in report["sources"].items():
        if item["status"] == "valid":
            lines.append(f"{exchange}: {item['price']} USDT | Thu thập {display(utc(item['collected_at']))}")
        else:
            lines.append(f"{exchange}: {'dữ liệu cũ' if item['status'] == 'stale' else 'thiếu dữ liệu'}")
    if report["valid"] >= 2:
        lines.extend([f"Cao nhất: {report['high_exchange']} {report['high']} USDT",
                      f"Thấp nhất: {report['low_exchange']} {report['low']} USDT",
                      f"Chênh lệch: {report['spread']} USDT ({Decimal(report['spread_percent']):.4f}%)"])
    if threshold is not None:
        lines.append(f"Ngưỡng: {threshold}%")
    lines.extend([f"Nguồn hợp lệ: {report['valid']}/3", f"Thời điểm tạo thông báo: {display(now)}"])
    return "\n".join(lines)


class Telegram:
    def __init__(self):
        self.enabled = os.getenv("TELEGRAM_ENABLED", "false").lower() == "true"
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat = os.getenv("TELEGRAM_CHAT_ID")
        if self.enabled and not (self.token and self.chat):
            raise ValueError("Telegram enabled without token or chat ID")
        self.interval = max(60, int(os.getenv("TELEGRAM_REPORT_INTERVAL", "300")))
        self.threshold = Decimal(os.getenv("TELEGRAM_SPREAD_THRESHOLD", "0.20"))
        self.cooldown = max(60, int(os.getenv("TELEGRAM_COOLDOWN", "600")))
        self.symbols = set(os.getenv("TELEGRAM_SYMBOLS", "BTC,ETH,SOL,XRP,ADA").split(","))

    def deliver(self, text):
        with httpx.Client(timeout=5) as http:
            for attempt in range(3):
                try:
                    response = http.post(f"https://api.telegram.org/bot{self.token}/sendMessage",
                                         json={"chat_id": self.chat, "text": text})
                except httpx.ConnectError:
                    if attempt == 2:
                        return "failed"
                    time.sleep(2 ** attempt)
                    continue
                except httpx.TransportError:
                    return "delivery_unknown"
                if response.status_code == 429:
                    delay = int(response.json().get("parameters", {}).get("retry_after", 1))
                    if not 0 <= delay <= 15 or attempt == 2:
                        return "failed"
                    time.sleep(delay)
                    continue
                return "sent" if response.is_success and response.json().get("ok") else "failed"
        return "failed"

    def record(self, postgres, reports, now):
        latest = {}
        for report in reports:
            latest[report["symbol"]] = report
        for report in latest.values():
            symbol, end = report["symbol"], utc(report["end"])
            if symbol.split("/")[0] not in self.symbols or not report["valid"]:
                continue
            if not 0 <= (now - end).total_seconds() <= min(120, self.interval):
                continue
            kinds = [("report", self.interval)]
            if "spread_percent" in report and Decimal(report["spread_percent"]) >= self.threshold:
                kinds.append(("spread", self.cooldown))
            for kind, cooldown in kinds:
                body = preview(report, now, kind, self.threshold if kind == "spread" else None)
                with postgres.db() as db:
                    db.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (symbol + kind,))
                    recent = db.execute("""SELECT 1 FROM alerts WHERE symbol=%s AND kind=%s
                                           AND window_end > %s LIMIT 1""",
                                        (symbol, kind, end - timedelta(seconds=cooldown))).fetchone()
                    if recent:
                        continue
                    inserted = db.execute("""INSERT INTO alerts(symbol,window_end,kind,state,body)
                        VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING symbol""",
                                          (symbol, end, kind, "reserved" if self.enabled else "dry_run", body)).fetchone()
                if self.enabled and inserted:
                    state = self.deliver(body + f"\nThời điểm gửi: {display(datetime.now(TZ))}")
                    with postgres.db() as db:
                        db.execute("UPDATE alerts SET state=%s WHERE symbol=%s AND window_end=%s AND kind=%s",
                                   (state, symbol, end, kind))
                    time.sleep(1)
