from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.models.agent import AgentProfile, AgentProfileRepository
from giga_agent.models.mcp_server import McpServerRepository
from giga_agent.models.llm import LLMRepository
from giga_agent.models.skill import SkillRepository
from giga_agent.modules.skills.service import SkillsService
from giga_agent.sandbox.manager import SandboxManager
from giga_agent.sandbox.manager.runtime_factory import SandboxRuntimeFactory
from giga_agent.subagents.parser import ParsedAgentManifest, parse_agent_manifest
from giga_agent.subagents.schema import (
    AgentCapabilityPolicy,
    AgentSkillRequirement,
    AgentToolRules,
)

if TYPE_CHECKING:
    from giga_agent.core.agent.base import BaseAgent
    from giga_agent.models.users import UserShort


@dataclass(frozen=True)
class AgentDefinition:
    ref: str
    source: Literal["builtin", "custom"]
    id: str
    name: str
    description: str
    prompt: str
    tags: tuple[str, ...]
    icon: str | None
    skills: tuple[AgentSkillRequirement, ...]
    modules: tuple[str, ...]
    connectors: tuple[str, ...]
    tools: AgentToolRules
    examples: tuple[str, ...]
    enabled: bool = True
    readiness: Literal["ready", "needs_setup"] = "ready"
    missing: tuple[dict[str, str], ...] = ()
    profile_id: uuid.UUID | None = None
    llm_id: uuid.UUID | None = None
    skill_names: tuple[str, ...] = ()
    mcp_server_ids: tuple[uuid.UUID, ...] = ()
    allowed_tool_effects: tuple[str, ...] = ("read",)
    manifest_path: Path | None = None

    def public_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ref": self.ref,
            "id": self.id,
            "source": self.source,
            "name": self.name,
            "description": self.description,
            "prompt": self.prompt,
            "tags": list(self.tags),
            "icon": self.icon,
            "modules": list(self.modules),
            "examples": list(self.examples),
            "enabled": self.enabled,
            "readiness": self.readiness,
            "missing": list(self.missing),
            "profile_id": self.profile_id,
            "llm_id": self.llm_id,
        }
        if self.source == "builtin":
            result.update(
                {
                    "skills": [skill.model_dump() for skill in self.skills],
                    "connectors": list(self.connectors),
                    "tools": self.tools.model_dump(),
                }
            )
        else:
            result.update(
                {
                    "skill_names": list(self.skill_names),
                    "mcp_server_ids": [str(item) for item in self.mcp_server_ids],
                    "allowed_tool_effects": list(self.allowed_tool_effects),
                }
            )
        return result


class AgentRegistry:
    def __init__(self, agent: "BaseAgent"):
        self.agent = agent
        self._builtins = self._load_builtins()

    def _load_builtins(self) -> dict[str, AgentDefinition]:
        definitions: dict[str, AgentDefinition] = {}
        plain_ids: dict[str, str] = {}
        for module in self.agent.all_modules:
            for configured_path in module.get_agents(agent=self.agent):
                path = Path(configured_path)
                if not path.is_absolute():
                    path = Path(module.module_path) / path
                parsed: ParsedAgentManifest = parse_agent_manifest(path)
                manifest = parsed.metadata
                ref = f"builtin:{module.id}:{manifest.id}"
                if ref in definitions:
                    raise ValueError(f"duplicate built-in agent ref: {ref}")
                previous = plain_ids.get(manifest.id)
                if previous is not None:
                    raise ValueError(
                        f"duplicate built-in agent id {manifest.id!r}: {previous}, {ref}"
                    )
                plain_ids[manifest.id] = ref
                definitions[ref] = AgentDefinition(
                    ref=ref,
                    source="builtin",
                    id=manifest.id,
                    name=manifest.name,
                    description=manifest.description,
                    prompt=parsed.prompt,
                    tags=tuple(manifest.tags),
                    icon=manifest.icon,
                    skills=tuple(manifest.skills),
                    modules=tuple(manifest.modules),
                    connectors=tuple(manifest.connectors),
                    tools=manifest.tools,
                    examples=tuple(manifest.examples),
                    manifest_path=parsed.path,
                )
        return definitions

    @property
    def builtins(self) -> tuple[AgentDefinition, ...]:
        return tuple(self._builtins.values())

    def get_builtin(self, ref: str) -> AgentDefinition | None:
        return self._builtins.get(ref)

    async def list_for_cli(
        self,
        user: "UserShort",
        *,
        config=None,
    ) -> list[AgentDefinition]:
        """List built-in agents without consulting the application database."""
        return [
            await self._with_cli_readiness(user, definition, config=config)
            for definition in self.builtins
        ]

    async def resolve_for_cli(
        self,
        user: "UserShort",
        ref: str,
        *,
        require_runnable: bool = False,
        config=None,
    ) -> AgentDefinition | None:
        """Resolve a built-in agent from manifests and CLI runtime config only."""
        for definition in await self.list_for_cli(user, config=config):
            if definition.ref == ref or (
                definition.source == "builtin" and definition.id == ref
            ):
                if require_runnable and (
                    not definition.enabled or definition.readiness != "ready"
                ):
                    return None
                return definition
        return None

    @staticmethod
    async def _custom_from_profile(
        repository: AgentProfileRepository, profile: AgentProfile
    ) -> AgentDefinition:
        skill_bindings = await repository.skill_bindings(profile.id)
        mcp_bindings = await repository.mcp_bindings(profile.id)
        capability_policy = AgentCapabilityPolicy.model_validate(
            profile.tool_policy or {}
        )
        skill_names = tuple(binding.requirement_name for binding in skill_bindings)
        return AgentDefinition(
            ref=f"db:{profile.id}",
            source="custom",
            id=str(profile.id),
            name=profile.name or "Unnamed agent",
            description=profile.description or "",
            prompt=profile.prompt or "",
            tags=tuple(profile.tags or []),
            icon=profile.icon,
            skills=tuple(
                AgentSkillRequirement(
                    name=binding.requirement_name,
                    source=binding.source,
                    ref=binding.source_ref,
                )
                for binding in skill_bindings
            ),
            modules=tuple(profile.modules or []),
            connectors=(),
            tools=AgentToolRules(),
            examples=tuple(profile.examples or []),
            enabled=profile.is_enabled,
            profile_id=profile.id,
            llm_id=profile.llm_id,
            skill_names=skill_names,
            mcp_server_ids=tuple(
                binding.mcp_server_id
                for binding in mcp_bindings
                if binding.mcp_server_id is not None
            ),
            allowed_tool_effects=tuple(capability_policy.allowed_effects),
        )

    async def list_for_user(
        self,
        db: AsyncSession,
        user: "UserShort",
        *,
        cli: bool = False,
        config=None,
    ) -> list[AgentDefinition]:
        repository = AgentProfileRepository(db)
        profiles = [] if cli else await repository.list_for_owner(user.id)
        overrides = {p.builtin_ref: p for p in profiles if p.builtin_ref}
        result: list[AgentDefinition] = []
        for definition in self.builtins:
            override = overrides.get(definition.ref)
            effective = replace(
                definition,
                enabled=override.is_enabled if override else True,
                profile_id=override.id if override else None,
            )
            result.append(
                await self._with_readiness(
                    db, user, effective, override, config=config
                )
            )
        if not cli:
            for profile in profiles:
                if profile.source == "custom" and profile.builtin_ref is None:
                    definition = await self._custom_from_profile(repository, profile)
                    result.append(
                        await self._with_readiness(
                            db, user, definition, profile, config=config
                        )
                    )
        return result

    async def resolve(
        self,
        db: AsyncSession,
        user: "UserShort",
        ref: str,
        *,
        require_runnable: bool = False,
        cli: bool = False,
        config=None,
    ) -> AgentDefinition | None:
        for definition in await self.list_for_user(
            db, user, cli=cli, config=config
        ):
            if definition.ref == ref or (
                definition.source == "builtin" and definition.id == ref
            ):
                if require_runnable and (
                    not definition.enabled or definition.readiness != "ready"
                ):
                    return None
                return definition
        return None

    async def _with_readiness(
        self,
        db: AsyncSession,
        user: "UserShort",
        definition: AgentDefinition,
        profile: AgentProfile | None,
        config=None,
    ) -> AgentDefinition:
        missing: list[dict[str, str]] = []
        from giga_agent.core.agent.base import _disabled_module_ids

        disabled = _disabled_module_ids(config, user)
        module_ids = {
            module.id
            for module in self.agent.all_modules
            if module.label
            and module.id not in disabled
            and await module.is_enabled(user, config=config)
        }
        for module_id in definition.modules:
            if module_id not in module_ids:
                missing.append({"kind": "module", "id": module_id})

        if definition.source == "custom":
            try:
                resolved = await SandboxManager.get_cached_or_db(
                    user_id=user.id, session=db
                )
                sandbox = SandboxRuntimeFactory.build(
                    resolved.provider, resolved.sandbox
                )
            except Exception:
                sandbox = None
            available_skill_names = {
                item.name
                for item in await SkillsService(db).list_skills(user.id, sandbox)
                if item.is_enabled
            }
            for skill_name in definition.skill_names:
                if skill_name not in available_skill_names:
                    missing.append({"kind": "skill", "id": skill_name})

            readable_servers = await McpServerRepository(db).get_readable_for_user(
                user.id, only_active=True
            )
            readable_server_ids = {server.id for server in readable_servers}
            for server_id in definition.mcp_server_ids:
                if server_id not in readable_server_ids:
                    missing.append({"kind": "mcp_server", "id": str(server_id)})
            if profile is not None and any(
                binding.mcp_server_id is None
                for binding in await AgentProfileRepository(db).mcp_bindings(
                    profile.id
                )
            ):
                missing.append({"kind": "mcp_server", "id": "removed"})

            if definition.llm_id is not None:
                llm = await LLMRepository(db).get_by_id_readable(
                    definition.llm_id, user_id=user.id
                )
                if llm is None or not llm.is_active:
                    missing.append({"kind": "llm", "id": str(definition.llm_id)})
        else:
            skill_bindings = (
                await AgentProfileRepository(db).skill_bindings(profile.id)
                if profile is not None
                else []
            )
            skill_by_name = {
                binding.requirement_name: binding for binding in skill_bindings
            }
            installed = {
                skill.id: skill
                for skill in await SkillRepository(db).get_enabled_by_owner(user.id)
            }
            for requirement in definition.skills:
                binding = skill_by_name.get(requirement.name)
                if binding is None or binding.skill_id not in installed:
                    missing.append({"kind": "skill", "id": requirement.name})

            connector_bindings = (
                await AgentProfileRepository(db).connector_bindings(profile.id)
                if profile is not None
                else []
            )
            bound_by_catalog = {
                binding.catalog_id: binding.mcp_server_id
                for binding in connector_bindings
            }
            readable_servers = await McpServerRepository(db).get_readable_for_user(
                user.id, only_active=True
            )
            readable_by_id = {server.id: server for server in readable_servers}
            catalog_servers: dict[str, list] = {}
            for server in readable_servers:
                if server.catalog_id:
                    catalog_servers.setdefault(server.catalog_id, []).append(server)
            for catalog_id in definition.connectors:
                bound_id = bound_by_catalog.get(catalog_id)
                if bound_id is not None and bound_id in readable_by_id:
                    continue
                candidates = catalog_servers.get(catalog_id, [])
                if profile is None and len(candidates) == 1:
                    continue
                missing.append({"kind": "connector", "id": catalog_id})

        if definition.llm_id is not None:
            llm = await LLMRepository(db).get_by_id_readable(
                definition.llm_id, user_id=user.id
            )
            if llm is None or not llm.is_active:
                missing.append({"kind": "llm", "id": str(definition.llm_id)})

        if not getattr(user, "is_synthetic", False) and not getattr(
            user, "sandbox_provider_id", None
        ):
            missing.append({"kind": "sandbox", "id": "required"})
        return replace(
            definition,
            readiness="needs_setup" if missing else "ready",
            missing=tuple(missing),
        )

    async def _with_cli_readiness(
        self,
        user: "UserShort",
        definition: AgentDefinition,
        *,
        config=None,
    ) -> AgentDefinition:
        """Check only manifest/module readiness for a CLI built-in agent."""
        from giga_agent.core.agent.base import _disabled_module_ids

        disabled = _disabled_module_ids(config, user)
        modules_by_id = {module.id: module for module in self.agent.all_modules}
        enabled_modules = set()
        for module_id in definition.modules:
            module = modules_by_id.get(module_id)
            if (
                module is not None
                and module.label
                and module.id not in disabled
                and await module.is_enabled(user, config=config)
            ):
                enabled_modules.add(module_id)
        missing = [
            {"kind": "module", "id": module_id}
            for module_id in definition.modules
            if module_id not in enabled_modules
        ]
        return replace(
            definition,
            readiness="needs_setup" if missing else "ready",
            missing=tuple(missing),
        )
