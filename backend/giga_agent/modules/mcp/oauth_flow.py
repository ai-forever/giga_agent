"""OAuth2 discovery / DCR / token-exchange helpers for the MCP routes.

Reuses the mcp SDK building blocks (RFC 8414 / 9728 discovery, RFC 7591 dynamic
client registration) and performs the authorization-code + PKCE exchange. Used
by the out-of-band OAuth routes (``api/oauth.py``); the call-time refresh path
uses :class:`OAuthClientProvider` instead (see ``oauth_provider.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
from mcp.client.auth.oauth2 import resource_url_from_server_url
from mcp.client.auth.utils import (
    build_oauth_authorization_server_metadata_discovery_urls,
    build_protected_resource_metadata_discovery_urls,
    create_oauth_metadata_request,
    handle_auth_metadata_response,
    handle_protected_resource_response,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from giga_agent.core.logging import get_logger

logger = get_logger(__name__)

_HTTP_TIMEOUT = 15.0


@dataclass
class AuthServerInfo:
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: str | None
    scopes_supported: list[str] | None


async def discover_auth_server(server_url: str) -> AuthServerInfo:
    """Resolve the authorization server metadata for an MCP server URL."""
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        # 1) Protected Resource Metadata (RFC 9728) -> authorization server.
        auth_server_url: str | None = None
        for url in build_protected_resource_metadata_discovery_urls(None, server_url):
            try:
                resp = await client.get(url)
            except httpx.HTTPError:
                continue
            prm = await handle_protected_resource_response(resp)
            if prm is not None and prm.authorization_servers:
                auth_server_url = str(prm.authorization_servers[0])
                break

        # 2) Authorization Server Metadata (RFC 8414).
        for url in build_oauth_authorization_server_metadata_discovery_urls(
            auth_server_url, server_url
        ):
            try:
                request = create_oauth_metadata_request(url)
                resp = await client.send(request)
            except httpx.HTTPError:
                continue
            _continue, metadata = await handle_auth_metadata_response(resp)
            if metadata is not None:
                return AuthServerInfo(
                    authorization_endpoint=str(metadata.authorization_endpoint),
                    token_endpoint=str(metadata.token_endpoint),
                    registration_endpoint=(
                        str(metadata.registration_endpoint)
                        if metadata.registration_endpoint
                        else None
                    ),
                    scopes_supported=metadata.scopes_supported,
                )

    raise ValueError("Could not discover OAuth authorization server metadata")


async def register_client(
    *,
    server_url: str,
    registration_endpoint: str | None,
    redirect_uri: str,
    scope: str | None,
) -> OAuthClientInformationFull:
    """Perform Dynamic Client Registration (RFC 7591).

    POSTs directly to the discovered ``registration_endpoint``. We do NOT use the
    SDK ``create_client_registration_request`` helper: it ignores the metadata's
    registration endpoint when passed ``None`` and instead targets
    ``<base>/register``, which is wrong for servers whose endpoint lives at a
    different path (e.g. Bitrix24's ``/oauth/register/mcp/``).
    """
    if not registration_endpoint:
        raise ValueError("Authorization server does not support dynamic registration")

    body: dict[str, Any] = {
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "client_secret_post",
        "client_name": "GigaAgent",
    }
    if scope:
        body["scope"] = scope

    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.post(registration_endpoint, json=body)
    if resp.status_code >= 400:
        raise ValueError(
            f"Client registration failed ({resp.status_code}): {resp.text}"
        )
    return OAuthClientInformationFull.model_validate(resp.json())


def build_authorization_url(
    *,
    authorization_endpoint: str,
    client_id: str,
    redirect_uri: str,
    state: str,
    code_challenge: str,
    scope: str | None,
    server_url: str,
) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "resource": resource_url_from_server_url(server_url),
    }
    if scope:
        params["scope"] = scope
    sep = "&" if "?" in authorization_endpoint else "?"
    return f"{authorization_endpoint}{sep}{urlencode(params)}"


async def exchange_code(
    *,
    token_endpoint: str,
    code: str,
    code_verifier: str,
    redirect_uri: str,
    client_id: str,
    client_secret: str | None,
    server_url: str,
) -> OAuthToken:
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": code_verifier,
        "resource": resource_url_from_server_url(server_url),
    }
    if client_secret:
        data["client_secret"] = client_secret
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.post(
            token_endpoint,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    if resp.status_code >= 400:
        raise ValueError(f"Token exchange failed ({resp.status_code}): {resp.text}")
    return OAuthToken.model_validate(resp.json())
