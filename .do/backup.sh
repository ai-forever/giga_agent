#!/bin/bash
# Single restic backup of .giga_agent and .langgraph_api to Spaces
set -e

if [ -z "$RESTIC_REPOSITORY" ] || [ -z "$RESTIC_PASSWORD" ]; then
    exit 0
fi

for dir in /data/.giga_agent /data/.langgraph_api; do
    [ -d "$dir" ] || continue
    restic backup "$dir" \
        --exclude "*.lock" \
        --exclude "*.pid" \
        --exclude "*.sock" \
        --quiet
done

restic forget --keep-last 10 --keep-hourly 24 --keep-daily 7 --prune --quiet 2>/dev/null || true
