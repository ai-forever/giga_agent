import secrets

from cashews import cache

LOCAL_DOCKER_PROVIDER = "local_docker"
LOCAL_JUPYTER_PROVIDER = "local_jupyter"
ADMIN_ONLY_SANDBOX_PROVIDERS = {
    LOCAL_DOCKER_PROVIDER,
    LOCAL_JUPYTER_PROVIDER,
}


def is_admin_only_provider_type(provider_type: str) -> bool:
    return provider_type in ADMIN_ONLY_SANDBOX_PROVIDERS


def is_provider_type_allowed_for_user(
    provider_type: str,
    *,
    is_superuser: bool,
) -> bool:
    if is_superuser:
        return True
    return not is_admin_only_provider_type(provider_type)

def ensure_provider_type_creatable_by_user(
    provider_type: str,
    *,
    is_superuser: bool,
) -> None:
    if not is_superuser and is_admin_only_provider_type(provider_type):
        raise PermissionError("Access denied")


def filter_provider_types_for_user(
    provider_types: list[str],
    *,
    is_superuser: bool,
) -> list[str]:
    if is_superuser:
        return provider_types
    return [
        provider_type
        for provider_type in provider_types
        if is_provider_type_allowed_for_user(
            provider_type,
            is_superuser=is_superuser,
        )
    ]


# ----------------------------------------------------------------------
# Capability tokens for time-limited, port-scoped sandbox URLs (nginx mode)
# ----------------------------------------------------------------------
#
# In nginx mode the sandbox is published at
# ``https://{port}-sandbox-{sandbox_id_hex}.{domain}``. Besides the owner's
# main session cookie, access can be granted via a capability token scoped to a
# single ``(sandbox_id, port)`` pair that expires after
# ``SANDBOX_ACCESS_TTL_SEC``. The token is opaque and stored in Redis (cashews),
# so it is revoked when the sandbox stops.
#
# Flow: ``open_port`` mints a token and returns
# ``…/?{SANDBOX_ACCESS_QUERY_PARAM}={token}`` → nginx exchanges the query token
# for a host-only cookie via the grant endpoint (so the token leaves the
# address bar / Referer) → the ``auth_request`` endpoint validates the cookie
# token against Redis.

SANDBOX_ACCESS_KEY_PREFIX = "sbx-access"
SANDBOX_ACCESS_TTL_SEC = 10 * 3600
SANDBOX_ACCESS_QUERY_PARAM = "__sbx"


def sandbox_access_cookie_name(sandbox_id_hex: str) -> str:
    """Per-sandbox host-only cookie name carrying the capability token."""
    return f"sbx_{sandbox_id_hex}"


def sandbox_access_key(sandbox_id_hex: str, port: int, token: str) -> str:
    return f"{SANDBOX_ACCESS_KEY_PREFIX}:{sandbox_id_hex}:{port}:{token}"


def sandbox_access_match_pattern(sandbox_id_hex: str) -> str:
    return f"{SANDBOX_ACCESS_KEY_PREFIX}:{sandbox_id_hex}:*"


async def mint_sandbox_access_token(sandbox_id_hex: str, port: int) -> str:
    """Create a reusable capability token valid for ``SANDBOX_ACCESS_TTL_SEC``."""
    token = secrets.token_urlsafe(32)
    await cache.set(
        sandbox_access_key(sandbox_id_hex, port, token),
        "1",
        expire=SANDBOX_ACCESS_TTL_SEC,
    )
    return token


async def is_sandbox_access_token_valid(
    sandbox_id_hex: str, port: int, token: str | None
) -> bool:
    if not token:
        return False
    return await cache.get(sandbox_access_key(sandbox_id_hex, port, token)) is not None


async def revoke_sandbox_access_tokens(sandbox_id_hex: str) -> None:
    """Invalidate every capability token for a sandbox (e.g. on stop)."""
    try:
        await cache.delete_match(sandbox_access_match_pattern(sandbox_id_hex))
    except Exception:
        pass