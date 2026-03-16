import types
import unittest

from giga_agent.modules.github import GitHubModule


class GitHubModuleTests(unittest.IsolatedAsyncioTestCase):
    def test_get_secrets_contract(self):
        module = GitHubModule()
        self.assertEqual(
            module.get_secrets(),
            [
                {
                    "name": "GITHUB_PERSONAL_ACCESS_TOKEN",
                    "description": "GitHub Personal Access Token для доступа к GitHub API.",
                    "type": "pass",
                }
            ],
        )

    async def test_get_tools_hidden_without_secret(self):
        module = GitHubModule()
        user = types.SimpleNamespace(secrets={})
        tools = await module.get_tools(user=user, agent=object())
        self.assertEqual(tools, [])

    async def test_get_tools_available_with_secret(self):
        module = GitHubModule()
        user = types.SimpleNamespace(secrets={"GITHUB_PERSONAL_ACCESS_TOKEN": "token"})
        tools = await module.get_tools(user=user, agent=object())
        self.assertEqual(
            sorted(tool.name for tool in tools),
            sorted(["get_workflow_runs", "list_pull_requests", "get_pull_request"]),
        )
