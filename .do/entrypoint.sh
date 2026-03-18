#!/bin/bash
set -e

mkdir -p /data/.giga_agent /data/.langgraph_api

# --- Restic / DO Spaces persistence ---
if [ "${ENABLE_SPACES}" = "true" ] && [ -n "$SPACES_BUCKET" ]; then
    export AWS_ACCESS_KEY_ID="$SPACES_ACCESS_KEY_ID"
    export AWS_SECRET_ACCESS_KEY="$SPACES_SECRET_ACCESS_KEY"
    export AWS_DEFAULT_REGION="${SPACES_REGION:-us-east-1}"
    export RESTIC_REPOSITORY="s3:https://${SPACES_ENDPOINT}/${SPACES_BUCKET}/giga-agent/restic"
    export RESTIC_PASSWORD="${RESTIC_PASSWORD:-giga-agent-default-key}"

    echo "[entrypoint] Restoring from Spaces backup..."
    /scripts/restore.sh || echo "[entrypoint] Restore skipped or failed, starting fresh"
fi

# --- Start giga_agent ---
giga_agent dev --host 0.0.0.0 --port 8080 --no-reload &
APP_PID=$!

# --- Periodic backup loop (every 30s) ---
if [ -n "$RESTIC_REPOSITORY" ]; then
    (
        while true; do
            sleep 30
            /scripts/backup.sh 2>&1 || true
        done
    ) &
    BACKUP_PID=$!
fi

# --- Graceful shutdown: final backup, then exit ---
shutdown() {
    echo "[entrypoint] Shutting down..."
    kill "$APP_PID" 2>/dev/null || true
    wait "$APP_PID" 2>/dev/null || true
    if [ -n "$RESTIC_REPOSITORY" ]; then
        echo "[entrypoint] Final backup..."
        /scripts/backup.sh || true
        kill "$BACKUP_PID" 2>/dev/null || true
    fi
    exit 0
}
trap shutdown SIGTERM SIGINT

wait "$APP_PID"
