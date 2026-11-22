FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY worker/requirements.txt worker/requirements.txt
COPY distributed/requirements.txt distributed/requirements.txt
RUN pip install --no-cache-dir -r distributed/requirements.txt && useradd -u 10001 -m linuxck && mkdir /data && chown linuxck /data
COPY --chown=10001:10001 worker worker
COPY --chown=10001:10001 distributed distributed
USER linuxck
