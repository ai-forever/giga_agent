from types import SimpleNamespace
from unittest.mock import patch

from giga_agent.middlewares.usage_tracking import schedule_usage_record


def test_cli_does_not_schedule_usage_database_record() -> None:
    config = {
        "configurable": {
            "langgraph_auth_user": {
                "identity": "00000000-0000-0000-0000-000000000000"
            }
        }
    }

    with (
        patch(
            "giga_agent.middlewares.usage_tracking.get_settings",
            return_value=SimpleNamespace(giga_agent_runtime="cli"),
        ),
        patch("giga_agent.middlewares.usage_tracking.asyncio.create_task") as create_task,
    ):
        schedule_usage_record(config, "deepseek-v4-flash", {"input_tokens": 1})

    create_task.assert_not_called()
