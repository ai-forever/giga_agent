import os
import platform
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from giga_agent.sandbox.secure_exec.errors import SandboxAccessDeniedError
from giga_agent.sandbox.secure_exec.launch import SecureProcessConfig
from giga_agent.sandbox.secure_exec.linux_bwrap import (
    build_linux_bwrap_command,
    launch_linux_bwrap,
)
from giga_agent.sandbox.secure_exec.macos import (
    MacSandboxExecConfig,
    build_macos_sandbox_profile,
)
from giga_agent.sandbox.secure_exec.policy import (
    SandboxAccessPolicy,
    default_package_cache_write_roots,
    python_virtual_env_write_roots,
)


class SandboxAccessPolicyTests(unittest.TestCase):
    def test_default_read_all_without_deny_roots(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            policy = SandboxAccessPolicy(workspace_root=tmp_dir)

            self.assertTrue(policy.can_read(Path("/") / "tmp"))
            self.assertTrue(policy.can_read(Path.home() / ".ssh" / "id_rsa"))

    def test_explicit_deny_roots_block_reads(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir) / "workspace"
            denied_root = Path(tmp_dir) / "denied"
            workspace.mkdir()
            denied_root.mkdir()
            policy = SandboxAccessPolicy(
                workspace_root=workspace,
                deny_roots=[denied_root],
            )

            self.assertFalse(policy.can_read(denied_root / "secret.txt"))
            with self.assertRaises(SandboxAccessDeniedError):
                policy.assert_can_read(denied_root / "secret.txt")

    def test_read_only_root_does_not_allow_write(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            read_root = Path(tmp_dir) / "read"
            read_root.mkdir()
            policy = SandboxAccessPolicy(
                workspace_root=Path(tmp_dir) / "workspace",
                read_roots=[read_root],
            )

            self.assertTrue(policy.can_read(read_root / "file.txt"))
            self.assertFalse(policy.can_write(read_root / "file.txt"))

    def test_write_root_allows_write_and_delete(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            write_root = Path(tmp_dir) / "write"
            write_root.mkdir()
            policy = SandboxAccessPolicy(
                workspace_root=Path(tmp_dir) / "workspace",
                write_roots=[write_root],
            )

            self.assertTrue(policy.can_read(write_root / "file.txt"))
            self.assertTrue(policy.can_write(write_root / "file.txt"))
            self.assertTrue(policy.can_delete(write_root / "file.txt"))

    def test_python_virtual_env_write_roots_include_venv_root(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            venv = Path(tmp_dir) / ".venv"
            python = venv / "bin" / "python"
            python.parent.mkdir(parents=True)
            python.write_text("", encoding="utf-8")
            (venv / "pyvenv.cfg").write_text("", encoding="utf-8")

            self.assertIn(venv.resolve(), python_virtual_env_write_roots(python))

    def test_python_virtual_env_write_roots_ignore_non_venv_bin_parent(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            python = Path(tmp_dir) / "bin" / "python"
            python.parent.mkdir(parents=True)
            python.write_text("", encoding="utf-8")

            self.assertNotIn(
                Path(tmp_dir).resolve(),
                python_virtual_env_write_roots(python),
            )

    def test_default_package_cache_write_roots_include_posix_cache_on_macos(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            home = Path(tmp_dir) / "home"

            with (
                patch(
                    "giga_agent.sandbox.secure_exec.policy.platform.system",
                    return_value="Darwin",
                ),
                patch(
                    "giga_agent.sandbox.secure_exec.policy.Path.home",
                    return_value=home,
                ),
            ):
                roots = default_package_cache_write_roots()

        self.assertIn((home / ".cache").resolve(), roots)
        self.assertIn((home / "Library" / "Caches" / "uv").resolve(), roots)


class LinuxBubblewrapCommandTests(unittest.TestCase):
    def test_command_binds_root_readonly_and_masks_denied_paths(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir) / "workspace"
            write_root = Path(tmp_dir) / "write"
            workspace.mkdir()
            write_root.mkdir()
            policy = SandboxAccessPolicy(
                workspace_root=workspace,
                write_roots=[write_root],
                deny_roots=[Path.home() / ".ssh"],
            )

            command = build_linux_bwrap_command(
                command=["python", "-c", "print('ok')"],
                policy=policy,
                executable="/usr/bin/bwrap",
            )

        self.assertIn("--ro-bind", command)
        self.assertIn("/", command)
        self.assertIn("--tmpfs", command)
        self.assertIn(str(Path.home() / ".ssh"), command)
        self.assertIn("--bind", command)
        self.assertIn(str(write_root.resolve()), command)
        self.assertNotIn("--clearenv", command)

    def test_command_adds_unshare_net_for_none_network_mode(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            policy = SandboxAccessPolicy(
                workspace_root=tmp_dir,
                network_mode="none",
            )

            command = build_linux_bwrap_command(
                command=["true"],
                policy=policy,
                executable="/usr/bin/bwrap",
            )

        self.assertIn("--unshare-net", command)

    def test_command_omits_unshare_net_for_host_network_mode(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            policy = SandboxAccessPolicy(
                workspace_root=tmp_dir,
                network_mode="host",
            )

            command = build_linux_bwrap_command(
                command=["true"],
                policy=policy,
                executable="/usr/bin/bwrap",
            )

        self.assertNotIn("--unshare-net", command)

    def test_launch_inherits_supplied_environment(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            env = os.environ.copy()
            env["GIGA_AGENT_TEST_ENV"] = "kept"
            policy = SandboxAccessPolicy(workspace_root=tmp_dir)
            proc = Mock(pid=1234)

            with (
                patch(
                    "giga_agent.sandbox.secure_exec.linux_bwrap.shutil.which",
                    return_value="/usr/bin/bwrap",
                ),
                patch(
                    "giga_agent.sandbox.secure_exec.linux_bwrap.subprocess.Popen",
                    return_value=proc,
                ) as popen_mock,
            ):
                launch = launch_linux_bwrap(
                    SecureProcessConfig(
                        command=["true"],
                        policy=policy,
                        env=env,
                    )
                )

        self.assertEqual(launch.process, proc)
        self.assertEqual(
            popen_mock.call_args.kwargs["env"]["GIGA_AGENT_TEST_ENV"],
            "kept",
        )

    @unittest.skipUnless(
        platform.system() == "Linux" and shutil.which("bwrap"),
        "bubblewrap smoke test requires Linux and bwrap",
    )
    def test_real_bwrap_blocks_write_outside_write_roots(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir) / "workspace"
            outside = Path(tmp_dir) / "outside"
            workspace.mkdir()
            outside.mkdir()
            target = outside / "blocked.txt"
            policy = SandboxAccessPolicy(
                workspace_root=workspace,
                read_roots=[tmp_dir],
                write_roots=[],
                network_mode="none",
            )
            command = build_linux_bwrap_command(
                command=[
                    "python",
                    "-c",
                    (
                        "from pathlib import Path; "
                        f"Path({str(target)!r}).write_text('blocked')"
                    ),
                ],
                policy=policy,
                executable=shutil.which("bwrap") or "bwrap",
            )
            result = subprocess.run(
                command,
                cwd=str(workspace),
                capture_output=True,
                timeout=10,
                check=False,
            )

        if result.returncode == 0:
            self.fail("bwrap allowed a write outside writable roots")
        self.assertFalse(target.exists())


class MacSandboxExecProfileTests(unittest.TestCase):
    def test_profile_allows_macos_trust_services_for_tls_verification(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            profile = build_macos_sandbox_profile(
                MacSandboxExecConfig(
                    command=["python", "-m", "pip", "index", "versions", "pip"],
                    profile_path=Path(tmp_dir) / "profile.sb",
                    allow_outbound_network=True,
                )
            )

        self.assertIn('"com.apple.securityd"', profile)
        self.assertIn('"com.apple.securityd.xpc"', profile)
        self.assertIn('"com.apple.trustd"', profile)
        self.assertIn('"com.apple.trustd.agent"', profile)
