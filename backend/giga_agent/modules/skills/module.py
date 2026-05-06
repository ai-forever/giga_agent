"""SkillsModule — BaseModule providing Agent Skills to the agent."""

from __future__ import annotations

import re
from typing import Any, List, Optional

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool

from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.agent.types import AgentState
from giga_agent.core.db import get_session_factory
from giga_agent.core.logging import get_logger
from giga_agent.core.module import BaseModule
from giga_agent.models.users import UserShort
from giga_agent.modules.skills.prompts import (
    SKILLS_EXPLICIT_ACTIVATION_HINT,
    SKILLS_SYSTEM_PROMPT_HEADER,
)
from giga_agent.modules.skills.service import SkillsService
from giga_agent.modules.skills.tools import activate_skill
from giga_agent.modules.skills.api import router as skills_router
from giga_agent.sandbox.manager import SandboxManager
from giga_agent.sandbox.manager.runtime_factory import SandboxRuntimeFactory

logger = get_logger(__name__)

_SKILL_MENTION_RE = re.compile(r"(?:^|[\s])[@/]([\w-]+)", re.MULTILINE)


class SkillsModule(BaseModule):
    id: str = "skills"

    async def get_tools(
        self, user: UserShort | None, agent: BaseAgent
    ) -> List[BaseTool]:
        _ = user, agent
        return [activate_skill]

    async def get_instructions(
        self,
        user: UserShort | None,
        agent: BaseAgent,
        state: Optional[AgentState] = None,
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> str | None:
        _ = agent, state, config, kwargs
        if user is None:
            return None

        try:
            factory = await get_session_factory()
            async with factory() as session:
                sandbox = None
                try:
                    resolved = await SandboxManager.get_cached_or_db(
                        user_id=user.id,
                        session=session,
                    )
                    sandbox = SandboxRuntimeFactory.build(
                        resolved.provider,
                        resolved.sandbox,
                    )
                except Exception:
                    sandbox = None
                svc = SkillsService(session)
                skills = await svc.list_skills(user.id, sandbox)
        except Exception as e:
            logger.warning("skills: failed to list skills for prompt: %s", e)
            return None

        enabled = [s for s in skills if s.is_enabled]
        if not enabled:
            return None

        lines = [SKILLS_SYSTEM_PROMPT_HEADER]
        for s in enabled:
            desc = s.description or "(no description)"
            lines.append(f"- **{s.name}**: {desc}")
        lines.append("")

        return "\n".join(lines)

    async def extend_task(
        self,
        user: UserShort | None,
        task: str,
        state: AgentState,
        agent: BaseAgent,
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> str | None:
        _ = state, agent, config, kwargs
        if not task:
            return None

        mentions = _SKILL_MENTION_RE.findall(task)
        if not mentions:
            return None

        if user is None:
            return None

        try:
            factory = await get_session_factory()
            async with factory() as session:
                sandbox = None
                try:
                    resolved = await SandboxManager.get_cached_or_db(
                        user_id=user.id,
                        session=session,
                    )
                    sandbox = SandboxRuntimeFactory.build(
                        resolved.provider,
                        resolved.sandbox,
                    )
                except Exception:
                    sandbox = None
                svc = SkillsService(session)
                all_skills = await svc.list_skills(user.id, sandbox)
        except Exception:
            return None

        skill_names = {s.name for s in all_skills if s.is_enabled}

        hints: list[str] = []
        for mention in mentions:
            name = mention.lower()
            if name in skill_names:
                hints.append(SKILLS_EXPLICIT_ACTIVATION_HINT.format(name=name))

        return "\n".join(hints) if hints else None

    def get_api_router(self, **kwargs: Any):
        return skills_router
