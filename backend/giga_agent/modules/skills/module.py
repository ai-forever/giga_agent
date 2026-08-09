"""SkillsModule — BaseModule providing Agent Skills to the agent."""

from __future__ import annotations

import re
from typing import Any, List, Optional

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool

from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.agent.runtime_resolver import RuntimeResolver
from giga_agent.core.agent.types import AgentState
from giga_agent.core.db import get_session_factory
from giga_agent.core.logging import get_logger
from giga_agent.core.module import BaseModule
from giga_agent.models.users import UserShort
from giga_agent.modules.skills.api import router as skills_router
from giga_agent.modules.skills.prompts import (
    SKILLS_EXPLICIT_ACTIVATION_HINT,
    SKILLS_SYSTEM_PROMPT_HEADER,
)
from giga_agent.modules.skills.service import SkillsService
from giga_agent.modules.skills.tools import read_skill_manifest
from giga_agent.sandbox.manager.runtime_factory import SandboxRuntimeFactory

logger = get_logger(__name__)

_SKILL_MENTION_RE = re.compile(r"(?:^|[\s])[@/]([\w-]+(?:/[\w-]+)*)", re.MULTILINE)


class SkillsModule(BaseModule):
    id: str = "skills"

    async def _get_tools(
        self, user: UserShort | None, agent: BaseAgent, *, config=None, **kwargs
    ) -> List[BaseTool]:
        _ = user, agent
        return [read_skill_manifest]

    @staticmethod
    async def _resolve_sandbox(config: RunnableConfig | None):
        if config is None:
            return None
        try:
            resolver = RuntimeResolver.from_config(config)
            resolved = await resolver.get_sandbox()
            return SandboxRuntimeFactory.build(resolved.provider, resolved.sandbox)
        except Exception:
            return None

    async def get_instructions(
        self,
        user: UserShort | None,
        agent: BaseAgent,
        state: Optional[AgentState] = None,
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> str | None:
        _ = agent, state, kwargs
        if user is None:
            return None

        try:
            sandbox = await self._resolve_sandbox(config)
            factory = await get_session_factory()
            async with factory() as session:
                svc = SkillsService(session)
                skills = await svc.list_skills(user.id, sandbox)
        except Exception as e:
            logger.warning("skills: failed to list skills for prompt: %s", e)
            return None

        enabled = [s for s in skills if s.is_enabled]
        configurable = (config or {}).get("configurable") or {}
        if configurable.get("subagent_id"):
            from giga_agent.subagents.execution import resolve_execution_profile

            execution = await resolve_execution_profile(agent, user, config)
            allowed = execution.skill_names if execution is not None else frozenset()
            enabled = [s for s in enabled if s.name in allowed]
        if not enabled:
            return None

        lines = [SKILLS_SYSTEM_PROMPT_HEADER]
        for s in enabled:
            desc = s.description or "(no description)"
            lines.append(f"- `{s.name}` — {desc}")
        lines.append("")

        return "\n".join(lines)

    async def _load_enabled_skill_names(
        self,
        user: UserShort,
        config: RunnableConfig | None,
    ) -> set[str]:
        try:
            sandbox = await self._resolve_sandbox(config)
            factory = await get_session_factory()
            async with factory() as session:
                svc = SkillsService(session)
                all_skills = await svc.list_skills(user.id, sandbox)
        except Exception:
            return set()
        return {s.name for s in all_skills if s.is_enabled}

    async def extend_task(
        self,
        user: UserShort | None,
        task: str,
        state: AgentState,
        agent: BaseAgent,
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> str | None:
        _ = state, agent, kwargs
        if user is None:
            return None

        configurable = (config or {}).get("configurable") or {}
        selected_skills_raw = configurable.get("selected_skills") or []
        selected_skills: list[str] = [
            str(s).strip().lower() for s in selected_skills_raw if str(s).strip()
        ]
        mentions = [m.lower() for m in _SKILL_MENTION_RE.findall(task)] if task else []

        if not selected_skills and not mentions:
            return None

        skill_names = await self._load_enabled_skill_names(user, config)
        if not skill_names:
            return None

        seen: set[str] = set()
        hints: list[str] = []
        for name in [*selected_skills, *mentions]:
            if name in skill_names and name not in seen:
                seen.add(name)
                hints.append(SKILLS_EXPLICIT_ACTIVATION_HINT.format(name=name))

        return "\n".join(hints) if hints else None

    def get_api_router(self, **kwargs: Any):
        return skills_router
