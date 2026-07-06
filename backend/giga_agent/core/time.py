"""Shared timezone helpers.

The project has a single configured timezone (``GIGA_AGENT_TIMEZONE``) used
consistently across the agent clock, the scheduler and integrations, so that
"in N minutes" reasoning, cron interpretation and calendar writes all agree on
what a naive local time means.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from giga_agent.conf import GIGA_AGENT_TIMEZONE


def default_tz():
    """Project timezone: ``GIGA_AGENT_TIMEZONE``, else the system local tz."""
    if GIGA_AGENT_TIMEZONE:
        try:
            return ZoneInfo(GIGA_AGENT_TIMEZONE)
        except (ZoneInfoNotFoundError, ValueError, KeyError):
            pass
    # System local timezone (falls back to UTC if it can't be determined).
    return datetime.now().astimezone().tzinfo or timezone.utc


def resolve_tz(tz_name: str | None):
    """Resolve an explicit tz name, falling back to :func:`default_tz`."""
    if not tz_name:
        return default_tz()
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return default_tz()
