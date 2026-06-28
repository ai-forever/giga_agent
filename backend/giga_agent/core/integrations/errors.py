"""Typed errors for the integrations layer."""

from __future__ import annotations


class IntegrationError(Exception):
    """Base class for integration errors."""


class ReauthRequired(IntegrationError):
    """The stored credentials are missing, expired, or revoked.

    Raised by :meth:`IntegrationProvider.access_token` when no usable token can
    be produced (no token stored, or a refresh attempt was rejected). The user
    must re-run the connect flow.
    """

    def __init__(self, provider_key: str, message: str | None = None) -> None:
        self.provider_key = provider_key
        super().__init__(message or f"reauthorization required for '{provider_key}'")
