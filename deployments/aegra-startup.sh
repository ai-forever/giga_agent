#!/bin/sh
set -eu

cd /aegra-api
alembic -c /aegra-api/alembic.ini upgrade head

exec uvicorn aegra_api.main:app --host 0.0.0.0 --port 8000 "$@"

