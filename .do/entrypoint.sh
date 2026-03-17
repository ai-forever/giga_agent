#!/bin/bash
set -e

mkdir -p /data/.giga_agent /data/.langgraph_api

if [ -n "$DATABASE_URL" ]; then
    export GIGA_AGENT_DATABASE_URL="${DATABASE_URL/postgresql:\/\//postgresql+asyncpg:\/\/}"
    export POSTGRES_URI="${DATABASE_URL/postgresql:\/\//postgres:\/\/}"
fi

exec giga_agent dev --host 0.0.0.0 --port 8080 --no-reload
