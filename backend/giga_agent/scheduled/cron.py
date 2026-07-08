"""Cron helpers for scheduled tasks."""

from __future__ import annotations

from datetime import datetime, timezone

from croniter import croniter

# Re-exported for backwards compatibility; canonical home is giga_agent.core.time.
from giga_agent.core.time import default_tz, resolve_tz

__all__ = ["is_valid_cron", "default_tz", "resolve_tz", "compute_next_run"]


def is_valid_cron(expression: str) -> bool:
    return bool(expression) and croniter.is_valid(expression)


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
    tz = resolve_tz(tz_name)
    if after.tzinfo is None:
        after = after.replace(tzinfo=timezone.utc)
    base = after.astimezone(tz)
    itr = croniter(expression, base)
    nxt = itr.get_next(datetime)
    if nxt.tzinfo is None:
        nxt = nxt.replace(tzinfo=tz)
    return nxt.astimezone(timezone.utc)
