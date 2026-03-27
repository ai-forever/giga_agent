import subprocess
import unittest
from unittest.mock import Mock, patch

from giga_agent.cli.commands.dev import _run_langgraph_server_in_subprocess


class DevProcessSupervisorTests(unittest.TestCase):
    def test_fallback_stops_supervised_processes_when_child_shutdown_times_out(self):
        proc = Mock()
        proc.pid = 42424
        proc.poll.return_value = None
        proc.wait.side_effect = [
            subprocess.TimeoutExpired(cmd="langgraph", timeout=2.5),
            0,
        ]
        supervisor = Mock()
        supervisor.stop_all.return_value = []

        with patch(
            "giga_agent.cli.commands.dev.subprocess.Popen",
            return_value=proc,
        ), patch(
            "giga_agent.cli.commands.dev.get_process_supervisor",
            return_value=supervisor,
        ), patch(
            "giga_agent.cli.commands.dev.time.sleep",
            side_effect=KeyboardInterrupt,
        ), patch(
            "giga_agent.cli.commands.dev._terminate_process_group"
        ) as terminate_mock:
            rc = _run_langgraph_server_in_subprocess(
                host="localhost",
                port=9090,
                reload=True,
                graphs={"giga_agent": "giga_agent.agents.run:graph"},
                auth_path="/tmp/auth.py",
                http_config={"app": "giga_agent.agents.run:app"},
                log_level="INFO",
            )

        self.assertEqual(rc, 0)
        supervisor.stop_all.assert_called_once()
        self.assertEqual(
            terminate_mock.call_args_list,
            [
                unittest.mock.call(proc, force=False),
                unittest.mock.call(proc, force=True),
            ],
        )
