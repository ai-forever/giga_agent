"""Cron helpers for scheduled tasks."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter

from giga_agent.conf import GIGA_AGENT_TIMEZONE


def is_valid_cron(expression: str) -> bool:
    return bool(expression) and croniter.is_valid(expression)


def default_tz():
    """Default scheduling timezone: GIGA_AGENT_TIMEZONE, else the system local tz."""
    if GIGA_AGENT_TIMEZONE:
        try:
            return ZoneInfo(GIGA_AGENT_TIMEZONE)
        except (ZoneInfoNotFoundError, ValueError, KeyError):
            pass
    # System local timezone (falls back to UTC if it can't be determined).
    return datetime.now().astimezone().tzinfo or timezone.utc


def _resolve_tz(tz_name: str | None):
    if not tz_name:
        return default_tz()
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return default_tz()


def compute_next_run(
    expression: str,
    *,
    tz_name: str | None = None,
    after: datetime,
) -> datetime:
    """Return the next fire time strictly after ``after`` for a cron expression.

    Always returns a timezone-aware UTC datetime so it can be stored and compared
    consistently regardless of the task's configured timezone.
    """
    tz = _resolve_tz(tz_name)
    if after.tzinfo is None:
        after = after.replace(tzinfo=timezone.utc)
    base = after.astimezone(tz)
    itr = croniter(expression, base)
    nxt = itr.get_next(datetime)
    if nxt.tzinfo is None:
        nxt = nxt.replace(tzinfo=tz)
    return nxt.astimezone(timezone.utc)
