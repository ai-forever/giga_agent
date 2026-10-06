from giga_agent.core.agent.disabled_modules_prompt import (
    build_disabled_modules_prompt,
)
from giga_agent.core.module import BaseModule, SecretMetadata


class _PlainModule(BaseModule):
    id: str = "plain"
    label: str = "Погода"
    description: str = "Получение прогноза погоды"


class _SecretModule(BaseModule):
    id: str = "weather"
    label: str = "Погода"
    description: str = "Получение прогноза погоды"

    def get_secrets(self, **kwargs) -> list[SecretMetadata]:
        return [
            {
                "name": "OWM_API_KEY",
                "description": "API key OpenWeatherMap",
                "type": "pass",
            }
        ]


class _ProviderModule(BaseModule):
    id: str = "yandex_disk"
    label: str = "Яндекс.Диск"
    description: str = "Работа с файлами на Яндекс.Диске"

    def get_providers(self, **kwargs):
        class _Provider:
            label = "Яндекс.Диск"

        return [_Provider()]


class _ServiceModule(BaseModule):
    id: str = "service"
    label: str = ""
    description: str = "Служебный модуль"


def test_returns_none_for_empty_list():
    assert build_disabled_modules_prompt([]) is None


def test_lists_label_and_description():
    prompt = build_disabled_modules_prompt([_PlainModule()])
    assert prompt is not None
    assert "Погода" in prompt
    assert "Получение прогноза погоды" in prompt
    assert "Отключённые модули" in prompt


def test_includes_secret_connect_hint():
    prompt = build_disabled_modules_prompt([_SecretModule()])
    assert prompt is not None
    assert "OWM_API_KEY" in prompt
    assert "API key OpenWeatherMap" in prompt
    assert "подключить" in prompt.lower()


def test_includes_provider_connect_hint():
    prompt = build_disabled_modules_prompt([_ProviderModule()])
    assert prompt is not None
    assert "Яндекс.Диск" in prompt
    assert "интеграция" in prompt.lower()


def test_skips_service_modules_without_label():
    assert build_disabled_modules_prompt([_ServiceModule()]) is None
