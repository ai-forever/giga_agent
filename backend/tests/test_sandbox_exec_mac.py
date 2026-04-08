import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from giga_agent.utils.sandbox_exec_mac import (
    MacSandboxExecConfig,
    build_macos_sandbox_profile,
    launch_with_macos_sandbox,
)


class MacSandboxExecTests(unittest.TestCase):
    def test_build_profile_includes_allow_and_deny_rules(self):
        config = MacSandboxExecConfig(
            command=["python", "-m", "jupyter", "server"],
            profile_path=Path("/tmp/jupyter.sandbox.sb"),
            read_roots=[Path("/")],
            write_roots=[Path("/tmp/runtime")],
            deny_read_roots=[Path.home() / ".ssh"],
            local_network_port=9090,
        )

        profile = build_macos_sandbox_profile(config)

        self.assertIn('(allow file-read* (subpath "/"))', profile)
        self.assertIn(
            f'(deny file-read* (subpath "{Path.home() / ".ssh"}"))',
            profile,
        )
        self.assertIn(
            '(allow network-outbound (remote ip "localhost:9090"))',
            profile,
        )
        self.assertIn('(allow file-read* file-write* (subpath "/dev"))', profile)
        self.assertIn(
            f'(allow file-write* (subpath "{Path("/tmp/runtime").resolve()}"))',
            profile,
        )

    def test_build_profile_supports_all_loopback_ports(self):
        config = MacSandboxExecConfig(
            command=["python", "-m", "jupyter", "server"],
            profile_path=Path("/tmp/jupyter.sandbox.sb"),
            read_roots=[Path("/")],
            write_roots=[Path("/tmp/runtime")],
            allow_local_network_all_ports=True,
        )

        profile = build_macos_sandbox_profile(config)

        self.assertIn('(allow network-outbound (remote ip "localhost:*"))', profile)

    def test_launch_writes_profile_and_prefixes_sandbox_exec(self):
        proc = Mock(pid=4321)
        with tempfile.TemporaryDirectory() as tmp_dir:
            profile_path = Path(tmp_dir) / "profile.sb"
            config = MacSandboxExecConfig(
                command=["python", "-m", "jupyter", "server"],
                profile_path=profile_path,
                cwd=Path(tmp_dir),
                env={"A": "1"},
                read_roots=[Path("/")],
                write_roots=[Path(tmp_dir)],
                deny_read_roots=[Path.home() / ".ssh"],
                local_network_port=8888,
            )

            with patch(
                "giga_agent.utils.sandbox_exec_mac.subprocess.Popen",
                return_value=proc,
            ) as popen_mock:
                launch = launch_with_macos_sandbox(config)
                self.assertTrue(profile_path.is_file())

        self.assertIs(launch.process, proc)
        self.assertEqual(
            popen_mock.call_args.args[0][:3],
            [config.executable, "-f", str(profile_path.resolve())],
        )
        self.assertEqual(
            popen_mock.call_args.args[0][3:],
            ["python", "-m", "jupyter", "server"],
        )
        self.assertEqual(popen_mock.call_args.kwargs["cwd"], str(Path(tmp_dir).resolve()))
        self.assertEqual(popen_mock.call_args.kwargs["env"], {"A": "1"})
