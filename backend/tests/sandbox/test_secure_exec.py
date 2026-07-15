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
        self.assertIn((home / "Library" / "Caches" / "Cypress").resolve(), roots)
        self.assertIn((home / "Library" / "Caches" / "Homebrew").resolve(), roots)
        self.assertIn((home / "Library" / "Caches" / "ms-playwright").resolve(), roots)
        self.assertIn((home / "Library" / "Caches" / "puppeteer").resolve(), roots)
        # Puppeteer hardcodes ~/.cache/puppeteer cross-platform — must be writable
        # on macOS too, even though it violates the Library/Caches convention.
        self.assertIn((home / ".cache" / "puppeteer").resolve(), roots)
        # Chrome for Testing (used by Puppeteer) writes Crashpad state here.
        self.assertIn(
            (
                home
                / "Library"
                / "Application Support"
                / "Google"
                / "Chrome for Testing"
            ).resolve(),
            roots,
        )
        self.assertIn((home / ".matplotlib").resolve(), roots)
        self.assertIn((home / ".config" / "matplotlib").resolve(), roots)
        self.assertIn((home / ".cache" / "matplotlib").resolve(), roots)
        self.assertIn((home / "Library" / "Caches" / "matplotlib").resolve(), roots)
        self.assertIn(
            (home / "Library" / "Developer" / "Xcode" / "DerivedData").resolve(),
            roots,
        )
        self.assertIn((home / "Library" / "Caches" / "uv").resolve(), roots)
        self.assertIn(
            (home / "Library" / "Application Support" / "Cypress").resolve(), roots
        )
        self.assertIn(
            (home / "Library" / "Application Support" / "matplotlib").resolve(),
            roots,
        )

    def test_default_package_cache_write_roots_include_python_notebook_state(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            home = Path(tmp_dir) / "home"

            with (
                patch(
                    "giga_agent.sandbox.secure_exec.policy.platform.system",
                    return_value="Linux",
                ),
                patch(
                    "giga_agent.sandbox.secure_exec.policy.Path.home",
                    return_value=home,
                ),
            ):
                roots = default_package_cache_write_roots()

        self.assertIn((home / ".ipython").resolve(), roots)
        self.assertIn((home / ".jupyter").resolve(), roots)
        self.assertIn((home / ".matplotlib").resolve(), roots)
        self.assertIn((home / ".plotly").resolve(), roots)
        self.assertIn((home / ".bokeh").resolve(), roots)
        self.assertIn((home / ".imageio").resolve(), roots)
        self.assertIn((home / ".sympy").resolve(), roots)
        self.assertIn((home / "nltk_data").resolve(), roots)
        self.assertIn((home / ".config" / "matplotlib").resolve(), roots)
        self.assertIn((home / ".config" / "fontconfig").resolve(), roots)
        self.assertIn((home / ".cache" / "matplotlib").resolve(), roots)
        self.assertIn((home / ".cache" / "fontconfig").resolve(), roots)
        self.assertIn((home / ".cache" / "jupyter").resolve(), roots)
        self.assertIn((home / ".cache" / "plotly").resolve(), roots)
        self.assertIn((home / ".cache" / "bokeh").resolve(), roots)
        self.assertIn((home / ".cache" / "imageio").resolve(), roots)
        self.assertIn((home / ".cache" / "scikit-image").resolve(), roots)
        self.assertIn((home / ".cache" / "xarray_tutorial_data").resolve(), roots)
        self.assertIn((home / ".cache" / "librosa").resolve(), roots)
        self.assertIn((home / ".cache" / "numba").resolve(), roots)
        self.assertIn((home / ".local" / "share" / "jupyter").resolve(), roots)
        self.assertIn((home / ".local" / "share" / "nltk_data").resolve(), roots)
        self.assertIn((home / ".local" / "share" / "spacy").resolve(), roots)
        self.assertIn((home / ".cache" / "huggingface").resolve(), roots)
        self.assertIn((home / ".cache" / "torch").resolve(), roots)
        self.assertIn((home / ".cache" / "keras").resolve(), roots)

    def test_default_package_cache_write_roots_include_common_agent_tool_state(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            home = Path(tmp_dir) / "home"

            with patch(
                "giga_agent.sandbox.secure_exec.policy.Path.home",
                return_value=home,
            ):
                roots = default_package_cache_write_roots()

        self.assertIn((home / ".colima").resolve(), roots)
        self.assertIn((home / ".lima").resolve(), roots)
        self.assertIn((home / ".ollama").resolve(), roots)
        self.assertIn((home / ".orbstack").resolve(), roots)
        self.assertIn((home / ".swiftpm").resolve(), roots)
        self.assertIn((home / ".wdm").resolve(), roots)
        self.assertIn((home / "go").resolve(), roots)

    def test_default_package_cache_write_roots_include_docker_state(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            home = Path(tmp_dir) / "home"

            with patch(
                "giga_agent.sandbox.secure_exec.policy.Path.home",
                return_value=home,
            ):
                roots = default_package_cache_write_roots()

        self.assertIn((home / ".docker").resolve(), roots)


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

    def test_profile_allows_fsevents_for_file_watching(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            profile = build_macos_sandbox_profile(
                MacSandboxExecConfig(
                    command=["node", "watcher.js"],
                    profile_path=Path(tmp_dir) / "profile.sb",
                )
            )

        self.assertIn('"com.apple.FSEvents"', profile)

    def test_profile_allows_dev_workflow_mach_services(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            profile = build_macos_sandbox_profile(
                MacSandboxExecConfig(
                    command=["sh", "-lc", "echo dev"],
                    profile_path=Path(tmp_dir) / "profile.sb",
                )
            )

        self.assertIn('"com.apple.cfprefsd.agent"', profile)
        self.assertIn('"com.apple.cfprefsd.daemon"', profile)
        self.assertIn('"com.apple.amfid"', profile)
        self.assertIn('"com.apple.metadata.mds"', profile)
        self.assertIn('"com.apple.metadata.mds.spi"', profile)
        self.assertIn('"com.apple.system.opendirectoryd.api"', profile)
        self.assertIn("distributed_notifications", profile)

    def test_profile_allows_unix_domain_sockets(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            profile = build_macos_sandbox_profile(
                MacSandboxExecConfig(
                    command=["docker", "ps"],
                    profile_path=Path(tmp_dir) / "profile.sb",
                )
            )

        self.assertIn("(allow network-bind (local unix-socket))", profile)
        self.assertIn("(allow network-outbound (remote unix-socket))", profile)

    def test_profile_allows_codex_inspired_extras(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            profile = build_macos_sandbox_profile(
                MacSandboxExecConfig(
                    command=["true"],
                    profile_path=Path(tmp_dir) / "profile.sb",
                )
            )

        self.assertIn('(local-name "com.apple.cfprefsd.agent")', profile)
        self.assertIn('"com.apple.SecurityServer"', profile)
        self.assertIn('"com.apple.networkd"', profile)
        self.assertIn('"com.apple.ocspd"', profile)
        self.assertIn('"com.apple.bsd.dirhelper"', profile)
        self.assertIn('"com.apple.PowerManagement.control"', profile)
        self.assertIn('"RootDomainUserClient"', profile)
        self.assertIn(
            '(allow sysctl-write (sysctl-name "kern.grade_cputype"))', profile
        )
        self.assertIn("(socket-domain AF_SYSTEM)", profile)

    def test_profile_allows_headless_browser_minimum(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            profile = build_macos_sandbox_profile(
                MacSandboxExecConfig(
                    command=["node", "puppeteer.js"],
                    profile_path=Path(tmp_dir) / "profile.sb",
                )
            )

        self.assertIn('"com.apple.windowserver.active"', profile)
        self.assertIn('"com.apple.tccd"', profile)
        self.assertIn('"com.apple.fontd"', profile)
        self.assertIn('"com.apple.lsd"', profile)
        self.assertIn('"IOSurfaceRootUserClient"', profile)
        # Chromium IPC via per-pid mach-services (org.chromium.Chromium.*).
        # Verified empirically: launching playwright-chromium under this profile
        # fails on bootstrap_check_in (parent) and bootstrap_look_up (children)
        # without these regex-based rules.
        self.assertIn(
            '(allow mach-register (global-name-regex #"^org\\.chromium\\."))',
            profile,
        )
        self.assertIn(
            '(allow mach-lookup (global-name-regex #"^org\\.chromium\\."))',
            profile,
        )
        # Chrome for Testing (Puppeteer's default browser) uses a different
        # mach-service prefix. Verified empirically: launching puppeteer with
        # PUPPETEER_DANGEROUS_NO_SANDBOX=true under this profile fails on
        # com.google.chrome.for.testing.MachPortRendezvousServer without these.
        self.assertIn(
            '(allow mach-register (global-name-regex #"^com\\.google\\.chrome\\.for\\.testing\\."))',
            profile,
        )
        self.assertIn(
            '(allow mach-lookup (global-name-regex #"^com\\.google\\.chrome\\.for\\.testing\\."))',
            profile,
        )
