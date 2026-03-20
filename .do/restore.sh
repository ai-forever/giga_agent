#!/bin/bash
# Restore .giga_agent and .langgraph_api from the latest restic snapshot
set -e

if [ -z "$RESTIC_REPOSITORY" ] || [ -z "$RESTIC_PASSWORD" ]; then
    echo "[restore] Persistence not configured, skipping"
    exit 0
fi

# Check if repo is initialized; init if first run
if ! restic snapshots --latest 1 >/dev/null 2>&1; then
    echo "[restore] Initializing restic repository..."
    restic init
    echo "[restore] No snapshots yet, starting fresh"
    exit 0
fi

for dir in /data/.giga_agent /data/.langgraph_api; do
    SNAPSHOT_ID=$(restic snapshots --path "$dir" --latest 1 --json 2>/dev/null | python3 -c "import sys,json; s=json.load(sys.stdin); print(s[0]['id'] if s else '')" 2>/dev/null)
    if [ -n "$SNAPSHOT_ID" ]; then
        echo "[restore] Restoring $dir (snapshot ${SNAPSHOT_ID:0:8})"
        restic restore "$SNAPSHOT_ID" --target / --include "$dir"
    else
        echo "[restore] No snapshot for $dir, skipping"
    fi
done

echo "[restore] Done"
