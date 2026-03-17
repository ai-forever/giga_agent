FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "giga-agent" "langgraph-cli[inmem]"

WORKDIR /data

COPY .do/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV GIGA_AGENT_PROJECT_ROOT=/data/.giga_agent

EXPOSE 8080

ENTRYPOINT ["/entrypoint.sh"]
