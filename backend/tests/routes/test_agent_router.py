import types
import unittest
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from giga_agent.core.deps import get_agent
from giga_agent.modules.auth.api import get_current_active_user
from giga_agent.routes.agent import router


class _ModuleStub:
    def __init__(self, secrets):
        self._secrets = secrets

    def get_secrets(self):
        return self._secrets


class AgentRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.user = types.SimpleNamespace(id=uuid.uuid4(), is_active=True)
        self.app = FastAPI()
        self.app.include_router(router)

        async def _override_current_user():
            return self.user

        self.app.dependency_overrides[get_current_active_user] = _override_current_user
        self.client = TestClient(self.app)

    def test_get_agent_secrets_returns_flat_list(self):
        agent = types.SimpleNamespace(
            all_modules=[
                _ModuleStub(
                    [
                        {
                            "name": "openai_api_key",
                            "description": "OpenAI API key",
                            "type": "text",
                        }
                    ]
                ),
                _ModuleStub(
                    [
                        {
                            "name": "tavily_api_key",
                            "description": "Tavily API key",
                        }
                    ]
                ),
            ]
        )

        async def _override_agent():
            return agent

        self.app.dependency_overrides[get_agent] = _override_agent

        response = self.client.get("/agent/secrets")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            [
                {
                    "name": "openai_api_key",
                    "description": "OpenAI API key",
                    "type": "text",
                },
                {
                    "name": "tavily_api_key",
                    "description": "Tavily API key",
                    "type": "pass",
                },
            ],
        )

    def test_get_agent_secrets_deduplicates_by_name(self):
        agent = types.SimpleNamespace(
            all_modules=[
                _ModuleStub(
                    [
                        {
                            "name": "shared_key",
                            "description": "First description",
                            "type": "llm_id",
                        }
                    ]
                ),
                _ModuleStub(
                    [
                        {
                            "name": "shared_key",
                            "description": "Second description",
                            "type": "text",
                        }
                    ]
                ),
            ]
        )

        async def _override_agent():
            return agent

        self.app.dependency_overrides[get_agent] = _override_agent

        response = self.client.get("/agent/secrets")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            [
                {
                    "name": "shared_key",
                    "description": "First description",
                    "type": "llm_id",
                }
            ],
        )

    def test_get_agent_secrets_empty_when_no_module_secrets(self):
        agent = types.SimpleNamespace(all_modules=[_ModuleStub([]), _ModuleStub([])])

        async def _override_agent():
            return agent

        self.app.dependency_overrides[get_agent] = _override_agent

        response = self.client.get("/agent/secrets")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_get_agent_secrets_requires_auth(self):
        app = FastAPI()
        app.include_router(router)

        agent = types.SimpleNamespace(modules=[_ModuleStub([])])

        async def _override_agent():
            return agent

        app.dependency_overrides[get_agent] = _override_agent
        client = TestClient(app)

        response = client.get("/agent/secrets")

        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
