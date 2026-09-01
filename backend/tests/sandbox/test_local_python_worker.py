from __future__ import annotations

import asyncio
import base64
import tempfile
import unittest
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from giga_agent.sandbox.local_jupyter.worker_manager import LocalPythonWorkerManager


async def _collect_events(
    code_iter: AsyncGenerator[dict[str, Any], str],
    *,
    input_reply: str = '{"ok": true, "data": "nested result"}',
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    pending_reply: str | None = None
    while True:
        try:
            if pending_reply is None:
                event = await anext(code_iter)
            else:
                event = await code_iter.asend(pending_reply)
                pending_reply = None
        except StopAsyncIteration:
            return events
        events.append(event)
        if event["type"] == "input_request":
            pending_reply = input_reply


class LocalPythonWorkerManagerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.cwd = Path(self._tmp_dir.name)
        self.manager = LocalPythonWorkerManager()

    async def asyncTearDown(self) -> None:
        await self.manager.stop_all()
        self._tmp_dir.cleanup()

    def _run(self, kernel_id: str, code: str) -> AsyncGenerator[dict[str, Any], str]:
        return self.manager.run_code(
            kernel_id=kernel_id,
            code=code,
            envs=None,
            cwd=self.cwd,
            safe_execution=False,
            policy=None,
        )

    async def test_worker_preserves_state_per_kernel_and_emits_final_expression(self):
        first = await _collect_events(self._run("kernel-a", "value = 41"))
        second = await _collect_events(self._run("kernel-a", "value + 1"))
        isolated = await _collect_events(self._run("kernel-b", "'value' in globals()"))

        self.assertEqual(first, [])
        self.assertEqual(second, [{"type": "result", "data": {"text/plain": "42"}}])
        self.assertEqual(
            isolated,
            [{"type": "result", "data": {"text/plain": "False"}}],
        )

    async def test_worker_streams_output_and_internal_input_rpc(self):
        events = await _collect_events(
            self._run(
                "kernel-input",
                'result = input(\'__GIGA_REPL_TOOL_CALL__:{"type": "tool_call"}\')\n'
                "print(result)",
            )
        )

        self.assertEqual(events[0]["type"], "input_request")
        self.assertEqual(events[1]["type"], "stdout")
        self.assertEqual(
            "".join(event["text"] for event in events[1:]),
            '{"ok": true, "data": "nested result"}\n',
        )

    async def test_worker_streams_stderr_and_serializes_one_kernel(self):
        first = asyncio.create_task(
            _collect_events(
                self._run(
                    "kernel-serialized",
                    "import sys, time\ntime.sleep(0.1)\nvalue = 41\n"
                    "print('warning', file=sys.stderr)",
                )
            )
        )
        await asyncio.sleep(0.02)
        second = await _collect_events(self._run("kernel-serialized", "value + 1"))
        first_events = await first

        self.assertEqual(second, [{"type": "result", "data": {"text/plain": "42"}}])
        self.assertEqual(first_events[0], {"type": "stderr", "text": "warning"})
        self.assertEqual(first_events[1], {"type": "stderr", "text": "\n"})

    async def test_worker_rejects_regular_input(self):
        events = await _collect_events(
            self._run("kernel-input-error", "input('Name: ')")
        )

        self.assertEqual(events[0]["type"], "error")
        self.assertEqual(events[0]["ename"], "RuntimeError")
        self.assertIn("Interactive input() is not supported", events[0]["evalue"])

    async def test_worker_captures_matplotlib_and_plotly_displays(self):
        matplotlib_events = await _collect_events(
            self._run(
                "kernel-matplotlib",
                "import matplotlib.pyplot as plt\nplt.plot([1, 2], [3, 4])\nplt.show()",
            )
        )
        image_payloads = [
            event["data"]["image/png"]
            for event in matplotlib_events
            if event["type"] == "display_data" and "image/png" in event["data"]
        ]
        self.assertEqual(len(image_payloads), 1)
        self.assertTrue(base64.b64decode(image_payloads[0]).startswith(b"\x89PNG"))

        plotly_events = await _collect_events(
            self._run(
                "kernel-plotly",
                "import plotly.graph_objects as go\n"
                "go.Figure(data=go.Bar(y=[1, 2])).show()",
            )
        )
        plotly_payloads = [
            event["data"]["application/vnd.plotly.v1+json"]
            for event in plotly_events
            if event["type"] == "display_data"
            and "application/vnd.plotly.v1+json" in event["data"]
        ]
        self.assertEqual(len(plotly_payloads), 1)
        self.assertEqual(plotly_payloads[0]["data"][0]["type"], "bar")

    async def test_worker_crash_returns_error_and_next_call_restarts(self):
        crashed = await _collect_events(
            self._run("kernel-crash", "import os\nos._exit(17)")
        )
        restarted = await _collect_events(self._run("kernel-crash", "6 * 7"))

        self.assertEqual(crashed[0]["type"], "error")
        self.assertEqual(crashed[0]["ename"], "PythonWorkerError")
        self.assertEqual(
            restarted,
            [{"type": "result", "data": {"text/plain": "42"}}],
        )

    async def test_stop_kernel_removes_worker(self):
        await _collect_events(self._run("kernel-stop", "value = 1"))
        self.assertIn("kernel-stop", self.manager._workers)

        await self.manager.stop_kernel("kernel-stop")

        self.assertNotIn("kernel-stop", self.manager._workers)
