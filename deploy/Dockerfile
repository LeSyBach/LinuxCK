FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY worker/requirements.txt worker/requirements.txt
COPY distributed/requirements.txt distributed/requirements.txt
RUN pip install --no-cache-dir -r distributed/requirements.txt && useradd -u 10001 -m linuxck && mkdir /data && chown linuxck /data
COPY --chown=10001:10001 worker worker
COPY --chown=10001:10001 distributed distributed
COPY deploy/setup.py deploy/.env.beszel.example deploy/beszel-agent.compose.yml /opt/linuxck/
USER linuxck

FROM runtime AS server
ENV LINUXCK_SETUP_ROLE=master
COPY deploy/master.compose.yml deploy/master.env.example deploy/beszel-hub.compose.yml /opt/linuxck/
CMD ["python", "-m", "uvicorn", "distributed.master:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]

FROM runtime AS worker
ENV LINUXCK_SETUP_ROLE=worker
COPY deploy/worker.compose.yml deploy/worker.env.example /opt/linuxck/
CMD ["python", "-m", "distributed.node"]
