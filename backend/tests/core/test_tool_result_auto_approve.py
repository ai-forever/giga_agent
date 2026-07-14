import unittest
from unittest.mock import AsyncMock, Mock, patch

from langchain_core.messages import AIMessage

from giga_agent.middlewares.tool_result import ToolResultMiddleware


def _state_with_tool_call(name: str, mcp_tools=None):
    msg = AIMessage(
        content="",
        tool_calls=[{"name": name, "args": {}, "id": "call-1", "type": "tool_call"}],
    )
    return {"messages": [msg], "mcp_tools": mcp_tools or []}


class ToolResultAutoApproveTests(unittest.IsolatedAsyncioTestCase):
    async def test_skips_interrupt_when_auto_approve_in_metadata(self):
        middleware = ToolResultMiddleware()
        state = _state_with_tool_call("python")
        config = {"metadata": {}, "configurable": {}}

        with patch(
            "giga_agent.middlewares.tool_result.get_thread_metadata",
            AsyncMock(return_value={"auto_approve": True}),
        ), patch(
            "giga_agent.middlewares.tool_result.interrupt"
        ) as interrupt_mock:
            result = await middleware.after_model(
                state, runtime=Mock(), config=config
            )

        interrupt_mock.assert_not_called()
        self.assertIsNone(result)

    async def test_after_model_reads_auto_approve_from_thread_metadata(self):
        # after_model honors the live thread metadata; configurable no longer
        # participates (the sync into metadata happens in before_agent).
        middleware = ToolResultMiddleware()
        state = _state_with_tool_call("python")
        config = {"metadata": {}, "configurable": {"auto_approve": False}}

        with patch(
            "giga_agent.middlewares.tool_result.get_thread_metadata",
            AsyncMock(return_value={"auto_approve": True}),
        ), patch(
            "giga_agent.middlewares.tool_result.interrupt"
        ) as interrupt_mock:
            result = await middleware.after_model(
                state, runtime=Mock(), config=config
            )

        interrupt_mock.assert_not_called()
        self.assertIsNone(result)

    async def test_interrupts_approve_when_auto_approve_off(self):
        middleware = ToolResultMiddleware()
        state = _state_with_tool_call("python")
        config = {"metadata": {}, "configurable": {}}

        with patch(
            "giga_agent.middlewares.tool_result.get_thread_metadata",
            AsyncMock(return_value={}),
        ), patch(
            "giga_agent.middlewares.tool_result.interrupt",
            return_value={"type": "approve"},
        ) as interrupt_mock:
            await middleware.after_model(state, runtime=Mock(), config=config)

        interrupt_mock.assert_called_once_with({"type": "approve"})

    async def test_frontend_actions_always_interrupt_even_with_auto_approve(self):
        middleware = ToolResultMiddleware()
        state = _state_with_tool_call("my_mcp", mcp_tools=[{"name": "my_mcp"}])
        config = {"metadata": {}, "configurable": {}}

        with patch(
            "giga_agent.middlewares.tool_result.get_thread_metadata",
            AsyncMock(return_value={"auto_approve": True}),
        ), patch(
            "giga_agent.middlewares.tool_result.interrupt",
            return_value={"type": "approve"},
        ) as interrupt_mock:
            await middleware.after_model(state, runtime=Mock(), config=config)

        interrupt_mock.assert_called_once()
        (payload,), _ = interrupt_mock.call_args
        self.assertEqual(payload["type"], "tool_call")
        self.assertEqual([a["name"] for a in payload["tools"]], ["my_mcp"])


class ToolResultBeforeAgentSyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_persists_to_metadata_when_missing(self):
        middleware = ToolResultMiddleware()
        config = {
            "metadata": {"thread_id": "t-1"},
            "configurable": {"thread_id": "t-1", "auto_approve": True},
        }
        update = AsyncMock()

        with patch(
            "giga_agent.middlewares.tool_result.get_thread_metadata",
            AsyncMock(return_value={}),
        ), patch(
            "giga_agent.middlewares.tool_result.update_thread_metadata", update
        ):
            await middleware.before_agent({}, runtime=Mock(), config=config)

        update.assert_awaited_once()
        args, kwargs = update.await_args
        self.assertEqual(args[1], "t-1")
        self.assertEqual(args[2], {"auto_approve": True})

    async def test_updates_metadata_when_value_changed(self):
        middleware = ToolResultMiddleware()
        config = {
            "metadata": {"thread_id": "t-1", "auto_approve": True},
            "configurable": {"thread_id": "t-1", "auto_approve": False},
        }
        update = AsyncMock()

        with patch(
            "giga_agent.middlewares.tool_result.get_thread_metadata",
            AsyncMock(return_value={"auto_approve": True}),
        ), patch(
            "giga_agent.middlewares.tool_result.update_thread_metadata", update
        ):
            await middleware.before_agent({}, runtime=Mock(), config=config)

        update.assert_awaited_once()
        args, _ = update.await_args
        self.assertEqual(args[2], {"auto_approve": False})

    async def test_noop_when_already_in_sync(self):
        middleware = ToolResultMiddleware()
        config = {
            "metadata": {"thread_id": "t-1", "auto_approve": True},
            "configurable": {"thread_id": "t-1", "auto_approve": True},
        }
        update = AsyncMock()

        with patch(
            "giga_agent.middlewares.tool_result.get_thread_metadata",
            AsyncMock(return_value={"auto_approve": True}),
        ), patch(
            "giga_agent.middlewares.tool_result.update_thread_metadata", update
        ):
            await middleware.before_agent({}, runtime=Mock(), config=config)

        update.assert_not_awaited()

    async def test_noop_on_resume_when_configurable_absent(self):
        # On resume configurable.auto_approve is absent — leave metadata untouched.
        middleware = ToolResultMiddleware()
        config = {
            "metadata": {"thread_id": "t-1", "auto_approve": True},
            "configurable": {"thread_id": "t-1"},
        }
        update = AsyncMock()

        with patch(
            "giga_agent.middlewares.tool_result.get_thread_metadata",
            AsyncMock(return_value={"auto_approve": True}),
        ), patch(
            "giga_agent.middlewares.tool_result.update_thread_metadata", update
        ):
            await middleware.before_agent({}, runtime=Mock(), config=config)

        update.assert_not_awaited()

    async def test_noop_for_temporary_thread(self):
        middleware = ToolResultMiddleware()
        config = {"metadata": {}, "configurable": {"auto_approve": True}}
        update = AsyncMock()

        with patch(
            "giga_agent.middlewares.tool_result.get_thread_metadata",
            AsyncMock(return_value={}),
        ), patch(
            "giga_agent.middlewares.tool_result.update_thread_metadata", update
        ):
            await middleware.before_agent({}, runtime=Mock(), config=config)

        update.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
