"""Shared helpers for parsing schedule input (used by tools and REST API)."""

from __future__ import annotations

from datetime import datetime, timezone

from giga_agent.models.scheduled_task import KIND_CRON, KIND_ONCE
from giga_agent.core.time import default_tz
from giga_agent.scheduled.cron import compute_next_run, is_valid_cron


class ScheduleParseError(ValueError):
    """Raised when a schedule expression cannot be interpreted."""


def parse_when(when: str) -> dict:
    """Interpret a free-form ``when`` into scheduling fields.

    Accepts either a cron expression ("0 9 * * 1") or an ISO-8601 datetime
    ("2026-06-29T09:00:00" or "...+03:00"). Returns a dict with kind, cron,
    run_at, timezone suitable for ScheduledTaskRepository.create.
    """
    value = (when or "").strip()
    if not value:
        raise ScheduleParseError("empty schedule")

    if is_valid_cron(value):
        run_at = compute_next_run(value, after=datetime.now(timezone.utc))
        return {
            "kind": KIND_CRON,
            "cron": value,
            "timezone": None,
            "run_at": run_at,
        }

    try:
        dt = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ScheduleParseError(
            "expected a cron expression or an ISO datetime"
        ) from exc

    # A naive datetime (e.g. "2026-06-29T09:00" from the agent) is meant in the
    # local/configured timezone, not UTC — otherwise it fires with an offset.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=default_tz())
    dt = dt.astimezone(timezone.utc)
    if dt <= datetime.now(timezone.utc):
        raise ScheduleParseError("run time is in the past")

    return {"kind": KIND_ONCE, "cron": None, "timezone": None, "run_at": dt}
