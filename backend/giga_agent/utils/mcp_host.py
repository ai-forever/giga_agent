"""Host classification for MCP server URLs.

Ported from the frontend logic in ``front/src/components/mcp/mcp-modal.tsx``
(``resolveUrlForTransport``). A URL is considered "local" when it points at
localhost, a loopback/link-local address or a private LAN range. Backend
execution of such servers is only allowed when ``GIGA_AGENT_RUNTIME_LOCAL`` is
enabled (see :mod:`giga_agent.modules.mcp.client`).

Classification is purely lexical on the literal host (no DNS resolution),
matching the frontend behaviour. DNS-rebinding is a known residual risk
documented in the migration plan.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit


def is_local_url(url: str) -> bool:
    """Return ``True`` if *url* points at a local/private host."""
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return False
    if not host:
        return False

    if host in ("localhost", "0.0.0.0", "::1") or host.endswith(".local"):
        return True

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False

    if ip.is_loopback or ip.is_link_local or ip.is_private:
        return True
    # 100.64.0.0/10 CGNAT — not flagged as ``is_private`` by ipaddress.
    if ip.version == 4 and ip in ipaddress.ip_network("100.64.0.0/10"):
        return True
    return False
