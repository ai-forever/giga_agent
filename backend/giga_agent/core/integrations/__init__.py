"""Provider-agnostic OAuth / token integrations.

A single per-user connection store (``core_oauth_connections``) and a provider
abstraction (:class:`IntegrationProvider`) shared by the backend MCP client and
by native agent modules that call a service's REST API directly.

This is core infrastructure, not an agent module: it ships no tools/prompt. Its
HTTP surface lives in ``routes/integrations.py`` (mounted like any other core
router), and its service entry points (:mod:`service`, :mod:`registry`) are
imported directly by ``core/module.py``, the MCP client, and native module tools.

See ``models/oauth_connection.py`` for the storage layer.
"""
