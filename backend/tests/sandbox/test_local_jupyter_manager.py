import asyncio
import os
import tempfile
import unittest
from contextlib import contextmanager
from unittest.mock import AsyncMock, Mock, patch

from giga_agent.conf import reset_settings_cache
from giga_agent.sandbox.local_jupyter.manager import (
    LocalJupyterHandle,
    LocalJupyterServerManager,
)


class LocalJupyterServerManagerTests(unittest.IsolatedAsyncioTestCase):
    @contextmanager
    def _patched_env(self, values: dict[str, str], *, clear: bool = False):
        reset_settings_cache()
        with patch.dict(os.environ, values, clear=clear):
            reset_settings_cache()
            try:
                yield
            finally:
                reset_settings_cache()

    async def test_ensure_started_serializes_concurrent_calls(self):
        manager = LocalJupyterServerManager()
        handle = LocalJupyterHandle(
            pid=12345,
            port=8888,
            token="token",
            base_url="http://127.0.0.1:8888",
            runtime_dir="/tmp/runtime",
            working_dir="/tmp/workdir",
            started_at=1.0,
        )
        manager._get_active_handle = AsyncMock(side_effect=[None, handle])  # type: ignore[method-assign]
        manager._start_new_server = AsyncMock(return_value=handle)  # type: ignore[method-assign]

        first, second = await asyncio.gather(
            manager.ensure_started(),
            manager.ensure_started(),
        )

        self.assertEqual(first, handle)
        self.assertEqual(second, handle)
        manager._start_new_server.assert_awaited_once()

    async def test_stop_uses_force_kill_when_process_does_not_exit_gracefully(self):
        manager = LocalJupyterServerManager()
        handle = LocalJupyterHandle(
            pid=43210,
            port=9999,
            token="token",
            base_url="http://127.0.0.1:9999",
            runtime_dir="/tmp/runtime",
            working_dir="/tmp/workdir",
            started_at=1.0,
        )

        manager._get_active_handle = AsyncMock(return_value=handle)  # type: ignore[method-assign]
        manager._wait_for_exit = AsyncMock(side_effect=[False, True])  # type: ignore[method-assign]
        manager._terminate_process_group = Mock()  # type: ignore[method-assign]
        manager._clear_state_unlocked = AsyncMock()  # type: ignore[method-assign]

        await manager.stop()

        self.assertEqual(
            manager._terminate_process_group.call_args_list,
            [
                unittest.mock.call(handle.pid, force=False),
                unittest.mock.call(handle.pid, force=True),
            ],
        )
        manager._clear_state_unlocked.assert_awaited_once()

    async def test_cleanup_stale_state_removes_dead_metadata(self):
        manager = LocalJupyterServerManager()
        handle = LocalJupyterHandle(
            pid=11111,
            port=7777,
            token="token",
            base_url="http://127.0.0.1:7777",
            runtime_dir="/tmp/runtime",
            working_dir="/tmp/workdir",
            started_at=1.0,
        )
        manager._read_metadata_file = Mock(return_value=handle)  # type: ignore[method-assign]
        manager._is_pid_alive = Mock(return_value=False)  # type: ignore[method-assign]
        manager._clear_state_unlocked = AsyncMock()  # type: ignore[method-assign]

        await manager.cleanup_stale_state()

        manager._clear_state_unlocked.assert_awaited_once()

    async def test_write_and_read_metadata_roundtrip(self):
        manager = LocalJupyterServerManager()
        handle = LocalJupyterHandle(
            pid=24680,
            port=8888,
            token="token",
            base_url="http://127.0.0.1:8888",
            runtime_dir="/tmp/runtime",
            working_dir="/tmp/workdir",
            started_at=1.0,
        )

        with tempfile.TemporaryDirectory() as tmp_dir, self._patched_env(
            {"GIGA_AGENT_PROJECT_ROOT": tmp_dir},
            clear=False,
        ):
            manager._write_metadata_file(handle)
            loaded = manager._read_metadata_file()

        self.assertEqual(loaded, handle)
