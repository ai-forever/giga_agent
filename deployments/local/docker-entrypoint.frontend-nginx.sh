#!/bin/sh
set -eu

INDEX_HTML="/usr/share/nginx/html/index.html"
BASE_URL="${GIGA_AGENT_BASE_URL:-/}"

if [ -f "$INDEX_HTML" ]; then
    escaped_base_url=$(printf '%s' "$BASE_URL" | sed 's/[\/&]/\\&/g')
    sed -i "s|<base href=\"/\"/>|<base href=\"${escaped_base_url}\"/>|" "$INDEX_HTML"
fi
