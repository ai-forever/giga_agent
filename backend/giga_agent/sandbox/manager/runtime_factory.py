from giga_agent.models.sandbox import (
    Sandbox,
    SandboxProvider,
    SandboxProviderSnapshot,
    SandboxSnapshot,
)
from giga_agent.sandbox.base import BaseSandbox
from giga_agent.sandbox.registry import SandboxRegistry


class SandboxRuntimeFactory:
    @staticmethod
    def merge_settings(
        provider: SandboxProvider | SandboxProviderSnapshot,
        sandbox: Sandbox | SandboxSnapshot,
    ) -> dict:
        settings = {**(provider.settings or {}), **(sandbox.settings or {})}
        settings["idle_timeout"] = provider.idle_timeout
        settings["owner_id"] = sandbox.owner_id
        return settings

    @classmethod
    def build(
        cls,
        provider: SandboxProvider | SandboxProviderSnapshot,
        sandbox: Sandbox | SandboxSnapshot,
    ) -> BaseSandbox:
        runtime_cls = SandboxRegistry.get(provider.type)
        return runtime_cls(**cls.merge_settings(provider, sandbox))
