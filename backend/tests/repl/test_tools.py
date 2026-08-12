import asyncio
import base64
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from giga_agent.modules.repl.module import ReplModule, get_user_secrets_prompt
from giga_agent.modules.repl.tools import (
    _build_attachment_info,
    _extract_upload_specs_from_display_data,
    _resolve_upload_prefix,
    get_user_secret_envs,
    normalize_secret_env_name,
    python,
    shell,
)
from giga_agent.core.agent.tool_policy import (
    ToolEffect,
    ToolPlanMode,
    resolve_tool_policy,
)


class ReplToolsTests(unittest.TestCase):
    def test_repl_module_can_disable_python_tool_and_prompt(self):
        module = ReplModule()
        config = {"configurable": {"no_python_tool": True}}

        with patch(
            "giga_agent.core.agent.runtime_resolver.RuntimeResolver.from_config",
            return_value=SimpleNamespace(has_sandbox=False),
        ):
            tools = asyncio.run(module._get_tools(None, None, config=config))

        self.assertEqual([tool.name for tool in tools], ["shell", "await_shell"])

        agent = SimpleNamespace(
            get_tools=AsyncMock(return_value=[python, shell]),
        )
        with patch(
            "giga_agent.modules.repl.module.get_sandbox_prompt",
            new=AsyncMock(return_value=""),
        ):
            prompt = asyncio.run(
                module.get_instructions(
                    SimpleNamespace(settings={}),
                    agent,
                    config=config,
                )
            )

        self.assertNotIn("КОД (python)", prompt)
        self.assertNotIn("repl_tools", prompt)
        self.assertNotIn("инструменте `python`", prompt)
        self.assertIn("ТЕРМИНАЛ (shell / await_shell)", prompt)

    def test_python_and_shell_are_explicitly_allowed_only_by_plan_filter(self):
        for repl_tool in (python, shell):
            with self.subTest(tool=repl_tool.name):
                policy = resolve_tool_policy(repl_tool)
                self.assertIsNotNone(policy)
                self.assertIs(policy.effect, ToolEffect.DESTRUCTIVE)
                self.assertIs(policy.plan_mode, ToolPlanMode.ALLOW)

    def test_repl_module_uses_worker_prompt_in_worker_cli_mode(self):
        module = ReplModule()
        agent = SimpleNamespace(get_tools=AsyncMock(return_value=[python, shell]))
        settings = SimpleNamespace(
            giga_agent_runtime="cli",
            giga_agent_cli_python_executor="worker",
        )

        with (
            patch("giga_agent.modules.repl.module.get_settings", return_value=settings),
            patch(
                "giga_agent.modules.repl.module.get_sandbox_prompt",
                new=AsyncMock(return_value=""),
            ),
        ):
            prompt = asyncio.run(
                module.get_instructions(SimpleNamespace(settings={}), agent)
            )

        self.assertIn("КОД (python worker)", prompt)
        self.assertIn("не используй Jupyter magic-команды", prompt)
        self.assertNotIn("Jupyter kernel", prompt)

    def test_normalize_secret_env_name_normalizes_shell_compatible_key(self):
        self.assertEqual(normalize_secret_env_name("api-key"), "API_KEY")
        self.assertEqual(normalize_secret_env_name(" 123 token "), "SECRET_123_TOKEN")
        self.assertEqual(normalize_secret_env_name("!!!"), "SECRET")

    def test_get_user_secret_envs_keeps_empty_values_and_overrides_collisions(self):
        user = type(
            "UserStub",
            (),
            {
                "settings": {
                    "contextSecrets": [
                        {"name": "api-key", "value": "first"},
                        {"name": "api key", "value": "second"},
                        {"name": "empty-secret", "value": ""},
                        {"name": "skip-me", "value": None},
                    ]
                }
            },
        )()

        self.assertEqual(
            get_user_secret_envs(user),
            {
                "API_KEY": "second",
                "EMPTY_SECRET": "",
            },
        )

    def test_get_user_secrets_prompt_uses_env_names_without_value_prefixes(self):
        user = type(
            "UserStub",
            (),
            {
                "settings": {
                    "contextSecrets": [
                        {
                            "name": "github-token",
                            "value": "ghp_secret_value",
                            "description": "PAT for GitHub API",
                        }
                    ]
                }
            },
        )()

        prompt = get_user_secrets_prompt(user)
        self.assertIn("os.environ", prompt)
        self.assertIn("ENV: GITHUB_TOKEN", prompt)
        self.assertIn("Описание: PAT for GitHub API", prompt)
        self.assertNotIn("ghp_", prompt)

        shell_prompt = get_user_secrets_prompt(user, include_python=False)
        self.assertNotIn("инструменте `python`", shell_prompt)
        self.assertIn("инструменте `shell`", shell_prompt)

    def test_extract_upload_specs_from_display_data_supported_mimes(self):
        specs = _extract_upload_specs_from_display_data(
            {
                "image/png": base64.b64encode(b"png").decode("ascii"),
                "audio/mpeg": base64.b64encode(b"mp3").decode("ascii"),
                "video/mp4": base64.b64encode(b"mp4").decode("ascii"),
                "application/vnd.plotly.v1+json": {"data": [1, 2], "layout": {}},
                "text/plain": "skip me",
            },
            upload_prefix="thread-42",
        )

        self.assertEqual(len(specs), 4)
        self.assertEqual(
            [item["file_type"] for item in specs],
            ["image", "audio", "video", "plotly_graph"],
        )
        self.assertTrue(specs[0]["file_name"].startswith("thread-42/"))
        self.assertTrue(specs[1]["file_name"].endswith(".mp3"))
        self.assertTrue(specs[2]["file_name"].endswith(".mp4"))
        self.assertTrue(specs[3]["file_name"].endswith(".plotly.json"))

    def test_extract_upload_specs_skips_invalid_base64(self):
        specs = _extract_upload_specs_from_display_data(
            {"image/png": "!!!not base64!!!"},
            upload_prefix="thread-42",
        )
        self.assertEqual(specs, [])

    def test_resolve_upload_prefix_uses_thread_id(self):
        runtime = type(
            "RuntimeStub", (), {"config": {"configurable": {"thread_id": "thr-1"}}}
        )()
        self.assertEqual(_resolve_upload_prefix(runtime), "thr-1")

    def test_resolve_upload_prefix_fallback_temporary(self):
        runtime = type("RuntimeStub", (), {"config": {"configurable": {}}})()
        prefix = _resolve_upload_prefix(runtime)
        self.assertTrue(prefix.startswith("temporary/"))
        self.assertEqual(len(prefix.split("/")), 2)

    def test_build_attachment_info_by_type(self):
        image = _build_attachment_info("image", "thread-1/a.png")
        audio = _build_attachment_info("audio", "thread-1/a.mp3")
        video = _build_attachment_info("video", "thread-1/a.mp4")
        plotly = _build_attachment_info("plotly_graph", "thread-1/a.plotly.json")

        self.assertIn("изображение", image)
        self.assertIn("![alt-текст](attachment:thread-1/a.png)", image)
        self.assertIn("аудиофайл", audio)
        self.assertIn("[аудио](attachment:thread-1/a.mp3)", audio)
        self.assertIn("видеофайл", video)
        self.assertIn("[видео](attachment:thread-1/a.mp4)", video)
        self.assertIn("график", plotly)
