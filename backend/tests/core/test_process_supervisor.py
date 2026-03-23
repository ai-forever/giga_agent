import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from giga_agent.core.process_supervisor import ManagedProcessRecord, ProcessSupervisor


class ProcessSupervisorTests(unittest.TestCase):
    def test_register_and_unregister_process_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            supervisor = ProcessSupervisor(runtime_dir=Path(tmp_dir))
            record = ManagedProcessRecord(
                kind="local_jupyter",
                pid=12345,
                pgid=12345,
                graceful_timeout_sec=5.0,
            )

            supervisor.register_process(record)
            listed = supervisor.list_processes()

            self.assertEqual(listed, [record])

            supervisor.unregister_process(kind="local_jupyter", pid=12345)
            self.assertEqual(supervisor.list_processes(), [])

    def test_unregister_process_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            supervisor = ProcessSupervisor(runtime_dir=Path(tmp_dir))
            supervisor.unregister_process(kind="local_jupyter", pid=99999)
            supervisor.unregister_process(kind="local_jupyter", pid=99999)

            self.assertEqual(supervisor.list_processes(), [])

    def test_list_processes_can_cleanup_stale_entries(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            supervisor = ProcessSupervisor(runtime_dir=Path(tmp_dir))
            alive_record = ManagedProcessRecord(
                kind="local_jupyter",
                pid=11111,
                pgid=11111,
            )
            stale_record = ManagedProcessRecord(
                kind="local_jupyter",
                pid=22222,
                pgid=22222,
            )
            supervisor.register_process(alive_record)
            supervisor.register_process(stale_record)
            supervisor._is_pid_alive = Mock(  # type: ignore[method-assign]
                side_effect=lambda pid: pid == alive_record.pid
            )

            listed = supervisor.list_processes(cleanup_stale=True)

            self.assertEqual(listed, [alive_record])
            self.assertEqual(supervisor.list_processes(), [alive_record])

    def test_stop_all_unregisters_process_after_successful_stop(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            supervisor = ProcessSupervisor(runtime_dir=Path(tmp_dir))
            record = ManagedProcessRecord(
                kind="local_jupyter",
                pid=33333,
                pgid=33333,
            )
            supervisor.register_process(record)
            supervisor._stop_record = Mock()  # type: ignore[method-assign]
            pid_states = iter([True, True, False])
            supervisor._is_pid_alive = Mock(  # type: ignore[method-assign]
                side_effect=lambda _pid: next(pid_states)
            )

            stopped = supervisor.stop_all()

            self.assertEqual(stopped, [record])
            self.assertEqual(supervisor.list_processes(), [])
