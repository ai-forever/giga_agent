#!/bin/bash
set -e

mkdir -p /data/.giga_agent /data/.langgraph_api

if [ -n "$DATABASE_URL" ]; then
    ASYNCPG_URL="${DATABASE_URL/postgresql:\/\//postgresql+asyncpg:\/\/}"
    # asyncpg does not recognize sslmode — replace with ssl
    ASYNCPG_URL="${ASYNCPG_URL/sslmode=/ssl=}"
    export GIGA_AGENT_DATABASE_URL="$ASYNCPG_URL"
    export POSTGRES_URI="${DATABASE_URL/postgresql:\/\//postgres:\/\/}"
fi

exec giga_agent dev --host 0.0.0.0 --port 8080 --no-reload
