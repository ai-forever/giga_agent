#!/bin/sh
set -eu

INDEX_HTML="/usr/share/nginx/html/index.html"
INDEX_HTML_GZ="${INDEX_HTML}.gz"
BASE_URL="${GIGA_AGENT_BASE_URL:-/}"

if [ -f "$INDEX_HTML" ]; then
    escaped_base_url=$(printf '%s' "$BASE_URL" | sed 's/[\/&]/\\&/g')
    sed -i \
        -e "s|<base href=\"/\"/>|<base href=\"${escaped_base_url}\"/>|" \
        -e "s|<base href=\"./\"/>|<base href=\"${escaped_base_url}\"/>|" \
        -e "s|<base href=\"/\">|<base href=\"${escaped_base_url}\"/>|" \
        -e "s|<base href=\"./\">|<base href=\"${escaped_base_url}\"/>|" \
        "$INDEX_HTML"

    if [ -f "$INDEX_HTML_GZ" ]; then
        gzip -c -9 "$INDEX_HTML" > "$INDEX_HTML_GZ"
    fi
fi
