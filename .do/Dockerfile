FROM python:3.11-slim

ARG RESTIC_VERSION=0.17.3

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    wget \
    bzip2 \
    && ARCH=$(dpkg --print-architecture) \
    && wget -q -O /tmp/restic.bz2 \
       "https://github.com/restic/restic/releases/download/v${RESTIC_VERSION}/restic_${RESTIC_VERSION}_linux_${ARCH}.bz2" \
    && bunzip2 /tmp/restic.bz2 \
    && mv /tmp/restic /usr/local/bin/restic \
    && chmod +x /usr/local/bin/restic \
    && apt-get purge -y wget bzip2 \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "giga-agent" "langgraph-cli[inmem]"

WORKDIR /data

COPY .do/entrypoint.sh .do/backup.sh .do/restore.sh /scripts/
RUN chmod +x /scripts/*.sh

ENV GIGA_AGENT_PROJECT_ROOT=/data/.giga_agent

EXPOSE 8080

ENTRYPOINT ["/scripts/entrypoint.sh"]
