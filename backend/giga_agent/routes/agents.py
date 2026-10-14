from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.core.db import get_session
from giga_agent.core.deps import get_agent
from giga_agent.models.agent import (
    AgentBindingUpdate,
    AgentProfileCreate,
    AgentProfileRepository,
)
from giga_agent.models.llm import LLMRepository
from giga_agent.models.mcp_server import McpServerRepository
from giga_agent.models.skill import SkillRepository
from giga_agent.models.users import UserShort
from giga_agent.modules.auth.api import get_current_active_user
from giga_agent.modules.skills.github import install_github_skill
from giga_agent.modules.skills.service import SkillInstallError, SkillsService
from giga_agent.sandbox.manager import SandboxManager
from giga_agent.sandbox.manager.runtime_factory import SandboxRuntimeFactory
from giga_agent.subagents.schema import AgentCapabilityPolicy

if TYPE_CHECKING:
    from giga_agent.core.agent.base import BaseAgent

router = APIRouter(prefix="/agents", tags=["agents"])


class AgentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=1024)
    prompt: str = Field(min_length=1, max_length=100_000)
    icon: str | None = Field(default=None, max_length=128)
    tags: list[str] = Field(default_factory=list)
    modules: list[str] | None = None
    mcp_server_ids: list[uuid.UUID] = Field(default_factory=list)
    skill_names: list[str] = Field(default_factory=list)
    allowed_tool_effects: list[str] = Field(default_factory=lambda: ["read"])
    examples: list[str] = Field(default_factory=list)
    llm_id: uuid.UUID | None = None
    is_enabled: bool = True


class AgentUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, min_length=1, max_length=1024)
    prompt: str | None = Field(default=None, min_length=1, max_length=100_000)
    icon: str | None = Field(default=None, max_length=128)
    tags: list[str] | None = None
    modules: list[str] | None = None
    mcp_server_ids: list[uuid.UUID] | None = None
    skill_names: list[str] | None = None
    allowed_tool_effects: list[str] | None = None
    examples: list[str] | None = None
    llm_id: uuid.UUID | None = None
    is_enabled: bool | None = None


class EnabledRequest(BaseModel):
    enabled: bool


class InstallSkillsRequest(BaseModel):
    confirmed: bool = False


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Agent not found")


async def _available_modules(agent: "BaseAgent", user: UserShort) -> list[dict[str, str]]:
    from giga_agent.core.agent.base import _disabled_module_ids

    disabled = _disabled_module_ids(None, user)
    result: list[dict[str, str]] = []
    for module in agent.all_modules:
        if not module.label or module.id in disabled:
            continue
        if not await module.is_enabled(user):
            continue
        result.append(
            {
                "id": module.id,
                "label": module.label,
                "description": module.description,
                "icon": module.icon,
            }
        )
    return result


async def _validate_modules(
    agent: "BaseAgent", user: UserShort, module_ids: list[str]
) -> None:
    available = {item["id"] for item in await _available_modules(agent, user)}
    unknown = sorted(set(module_ids) - available)
    if unknown:
        raise HTTPException(422, detail={"unknown_modules": unknown})


async def _validate_llm(db: AsyncSession, user_id: uuid.UUID, llm_id: uuid.UUID | None):
    if llm_id is None:
        return
    if await LLMRepository(db).get_by_id_readable(llm_id, user_id=user_id) is None:
        raise HTTPException(422, detail="LLM is unavailable")


async def _editor_skills(
    db: AsyncSession, user: UserShort
) -> list[Any]:
    try:
        resolved = await SandboxManager.get_cached_or_db(
            user_id=user.id, session=db
        )
        sandbox = SandboxRuntimeFactory.build(resolved.provider, resolved.sandbox)
    except Exception:
        sandbox = None
    return await SkillsService(db).list_skills(user.id, sandbox)


async def _validate_custom_capabilities(
    *,
    agent: "BaseAgent",
    user: UserShort,
    db: AsyncSession,
    modules: list[str],
    mcp_server_ids: list[uuid.UUID],
    skill_names: list[str],
    llm_id: uuid.UUID | None,
) -> tuple[list[dict[str, Any]], list[uuid.UUID]]:
    await _validate_modules(agent, user, modules)
    await _validate_llm(db, user.id, llm_id)

    available_servers = await McpServerRepository(db).get_readable_for_user(
        user.id, only_active=True
    )
    server_by_id = {server.id: server for server in available_servers}
    unique_server_ids = list(dict.fromkeys(mcp_server_ids))
    invalid_servers = [
        str(server_id)
        for server_id in unique_server_ids
        if server_id not in server_by_id
    ]
    if invalid_servers:
        raise HTTPException(
            422, detail={"unavailable_mcp_server_ids": invalid_servers}
        )

    available_skills = await _editor_skills(db, user)
    available_skill_names = {item.name for item in available_skills if item.is_enabled}
    unique_skill_names = list(dict.fromkeys(name.strip() for name in skill_names))
    invalid_skills = sorted(
        name for name in unique_skill_names if not name or name not in available_skill_names
    )
    if invalid_skills:
        raise HTTPException(422, detail={"unavailable_skill_names": invalid_skills})

    db_skills = {
        item.name: item
        for item in await SkillRepository(db).get_enabled_by_owner(user.id)
    }
    skill_rows = [
        {
            "requirement_name": name,
            "source": None,
            "source_ref": None,
            "skill_id": getattr(db_skills.get(name), "id", None),
        }
        for name in unique_skill_names
    ]
    return skill_rows, unique_server_ids


async def _definition_or_404(
    agent: "BaseAgent", db: AsyncSession, user: UserShort, agent_ref: str
):
    definition = await agent.subagent_registry.resolve(db, user, agent_ref)
    if definition is None:
        raise _not_found()
    return definition


@router.get("")
async def list_agents(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    agent: Annotated["BaseAgent", Depends(get_agent)],
) -> list[dict[str, Any]]:
    definitions = await agent.subagent_registry.list_for_user(db, current_user)
    return [item.public_dict() for item in definitions]


@router.get("/editor-options")
async def get_editor_options(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    agent: Annotated["BaseAgent", Depends(get_agent)],
) -> dict[str, Any]:
    servers = await McpServerRepository(db).get_readable_for_user(
        current_user.id, only_active=True
    )
    skills = await _editor_skills(db, current_user)
    llm_rows = await LLMRepository(db).list_readable_with_edit_for_user(
        user_id=current_user.id, only_active=True
    )
    return {
        "modules": await _available_modules(agent, current_user),
        "mcp_servers": [
            {"id": str(item.id), "name": item.name or str(item.id)}
            for item in servers
        ],
        "skills": [
            {
                "name": item.name,
                "description": item.description,
                "source_type": item.source_type,
            }
            for item in skills
            if item.is_enabled
        ],
        "llms": [
            {
                "id": str(item.id),
                "name": item.name or item.model_id,
                "model_id": item.model_id,
            }
            for item, _can_edit in llm_rows
        ],
    }


@router.get("/{agent_ref}")
async def get_agent_definition(
    agent_ref: str,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    agent: Annotated["BaseAgent", Depends(get_agent)],
) -> dict[str, Any]:
    definition = await _definition_or_404(agent, db, current_user, agent_ref)
    return definition.public_dict()


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_agent(
    request: AgentCreateRequest,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    agent: Annotated["BaseAgent", Depends(get_agent)],
) -> dict[str, Any]:
    capability_policy = AgentCapabilityPolicy(
        allowed_effects=request.allowed_tool_effects
    )
    modules = (
        request.modules
        if request.modules is not None
        else [item["id"] for item in await _available_modules(agent, current_user)]
    )
    skill_rows, mcp_server_ids = await _validate_custom_capabilities(
        agent=agent,
        user=current_user,
        db=db,
        modules=modules,
        mcp_server_ids=request.mcp_server_ids,
        skill_names=request.skill_names,
        llm_id=request.llm_id,
    )
    profile = await AgentProfileRepository(db).create_custom(
        current_user.id,
        AgentProfileCreate(
            name=request.name,
            description=request.description,
            prompt=request.prompt,
            icon=request.icon,
            tags=request.tags,
            modules=modules,
            tool_policy=capability_policy.model_dump(),
            examples=request.examples,
            llm_id=request.llm_id,
            is_enabled=request.is_enabled,
        ),
    )
    await AgentProfileRepository(db).replace_custom_bindings(
        profile.id, skills=skill_rows, mcp_server_ids=mcp_server_ids
    )
    definition = await _definition_or_404(agent, db, current_user, f"db:{profile.id}")
    return definition.public_dict()


@router.patch("/{agent_ref}")
async def update_agent(
    agent_ref: str,
    request: AgentUpdateRequest,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    agent: Annotated["BaseAgent", Depends(get_agent)],
) -> dict[str, Any]:
    if not agent_ref.startswith("db:"):
        raise HTTPException(405, detail="Built-in agents must be cloned before editing")
    try:
        profile_id = uuid.UUID(agent_ref.removeprefix("db:"))
    except ValueError as exc:
        raise _not_found() from exc
    repository = AgentProfileRepository(db)
    profile = await repository.get_for_owner(profile_id, current_user.id)
    if profile is None or profile.source != "custom":
        raise _not_found()
    values = request.model_dump(
        exclude_unset=True,
        exclude={"mcp_server_ids", "skill_names", "allowed_tool_effects"},
    )
    modules = request.modules if request.modules is not None else list(profile.modules or [])
    mcp_server_ids = (
        request.mcp_server_ids
        if request.mcp_server_ids is not None
        else [item.mcp_server_id for item in await repository.mcp_bindings(profile.id)]
    )
    skill_names = (
        request.skill_names
        if request.skill_names is not None
        else [item.requirement_name for item in await repository.skill_bindings(profile.id)]
    )
    allowed_effects = (
        request.allowed_tool_effects
        if request.allowed_tool_effects is not None
        else list(AgentCapabilityPolicy.model_validate(profile.tool_policy or {}).allowed_effects)
    )
    capability_policy = AgentCapabilityPolicy(allowed_effects=allowed_effects)
    skill_rows, mcp_server_ids = await _validate_custom_capabilities(
        agent=agent,
        user=current_user,
        db=db,
        modules=modules,
        mcp_server_ids=mcp_server_ids,
        skill_names=skill_names,
        llm_id=request.llm_id if "llm_id" in request.model_fields_set else profile.llm_id,
    )
    values["modules"] = modules
    values["tool_policy"] = capability_policy.model_dump()
    await repository.update(profile, values)
    await repository.replace_custom_bindings(
        profile.id, skills=skill_rows, mcp_server_ids=mcp_server_ids
    )
    definition = await _definition_or_404(agent, db, current_user, agent_ref)
    return definition.public_dict()


@router.delete("/{agent_ref}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    agent_ref: str,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    if not agent_ref.startswith("db:"):
        raise HTTPException(405, detail="Built-in agents cannot be deleted")
    try:
        profile_id = uuid.UUID(agent_ref.removeprefix("db:"))
    except ValueError as exc:
        raise _not_found() from exc
    repository = AgentProfileRepository(db)
    profile = await repository.get_for_owner(profile_id, current_user.id)
    if profile is None or profile.source != "custom":
        raise _not_found()
    await repository.delete(profile)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{agent_ref}/clone", status_code=status.HTTP_201_CREATED)
async def clone_agent(
    agent_ref: str,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    agent: Annotated["BaseAgent", Depends(get_agent)],
) -> dict[str, Any]:
    source = await _definition_or_404(agent, db, current_user, agent_ref)
    available_skill_names = {
        item.name for item in await _editor_skills(db, current_user) if item.is_enabled
    }
    skill_names = [
        item.name for item in source.skills if item.name in available_skill_names
    ]
    readable_servers = await McpServerRepository(db).get_readable_for_user(
        current_user.id, only_active=True
    )
    mcp_server_ids: list[uuid.UUID] = []
    for catalog_id in source.connectors:
        matches = [server for server in readable_servers if server.catalog_id == catalog_id]
        if len(matches) == 1:
            mcp_server_ids.append(matches[0].id)
    profile = await AgentProfileRepository(db).create_custom(
        current_user.id,
        AgentProfileCreate(
            name=f"{source.name} (копия)",
            description=source.description,
            prompt=source.prompt,
            icon=source.icon,
            tags=list(source.tags),
            modules=list(source.modules),
            tool_policy={"allowed_effects": ["read"]},
            examples=list(source.examples),
            llm_id=source.llm_id,
            is_enabled=True,
        ),
    )
    db_skills = {
        item.name: item
        for item in await SkillRepository(db).get_enabled_by_owner(current_user.id)
    }
    await AgentProfileRepository(db).replace_custom_bindings(
        profile.id,
        skills=[
            {
                "requirement_name": name,
                "source": None,
                "source_ref": None,
                "skill_id": getattr(db_skills.get(name), "id", None),
            }
            for name in skill_names
        ],
        mcp_server_ids=mcp_server_ids,
    )
    cloned = await _definition_or_404(agent, db, current_user, f"db:{profile.id}")
    return cloned.public_dict()


@router.put("/{agent_ref}/enabled")
async def set_agent_enabled(
    agent_ref: str,
    request: EnabledRequest,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    agent: Annotated["BaseAgent", Depends(get_agent)],
) -> dict[str, Any]:
    definition = await _definition_or_404(agent, db, current_user, agent_ref)
    repository = AgentProfileRepository(db)
    if definition.source == "builtin":
        profile = await repository.ensure_builtin_override(
            current_user.id, definition.ref
        )
        if not await repository.skill_bindings(
            profile.id
        ) and not await repository.connector_bindings(profile.id):
            await repository.replace_bindings(
                profile.id,
                skills=[
                    {
                        "requirement_name": item.name,
                        "source": item.source,
                        "source_ref": item.ref,
                    }
                    for item in definition.skills
                ],
                connectors=[{"catalog_id": item} for item in definition.connectors],
            )
    else:
        assert definition.profile_id is not None
        profile = await repository.get_for_owner(definition.profile_id, current_user.id)
        if profile is None:
            raise _not_found()
    await repository.update(profile, {"is_enabled": request.enabled})
    updated = await _definition_or_404(agent, db, current_user, agent_ref)
    return updated.public_dict()


@router.get("/{agent_ref}/requirements")
async def get_agent_requirements(
    agent_ref: str,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    agent: Annotated["BaseAgent", Depends(get_agent)],
) -> dict[str, Any]:
    definition = await _definition_or_404(agent, db, current_user, agent_ref)
    if definition.source == "custom":
        return {
            "readiness": definition.readiness,
            "missing": list(definition.missing),
            "modules": list(definition.modules),
            "mcp_server_ids": [str(item) for item in definition.mcp_server_ids],
            "skill_names": list(definition.skill_names),
            "allowed_tool_effects": list(definition.allowed_tool_effects),
        }
    return {
        "readiness": definition.readiness,
        "missing": list(definition.missing),
        "skills": [item.model_dump() for item in definition.skills],
        "connectors": list(definition.connectors),
        "modules": list(definition.modules),
    }


@router.put("/{agent_ref}/bindings")
async def update_agent_bindings(
    agent_ref: str,
    request: AgentBindingUpdate,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    agent: Annotated["BaseAgent", Depends(get_agent)],
) -> dict[str, Any]:
    definition = await _definition_or_404(agent, db, current_user, agent_ref)
    if definition.source != "builtin":
        raise HTTPException(
            405, detail="Custom agent capabilities are edited via the agent profile"
        )
    await _validate_llm(db, current_user.id, request.llm_id)
    repository = AgentProfileRepository(db)
    if definition.source == "builtin":
        profile = await repository.ensure_builtin_override(
            current_user.id, definition.ref
        )
    else:
        assert definition.profile_id is not None
        profile = await repository.get_for_owner(definition.profile_id, current_user.id)
        if profile is None:
            raise _not_found()

    existing_skill_bindings = {
        item.requirement_name: item
        for item in await repository.skill_bindings(profile.id)
    }
    available_skills = {
        item.id: item
        for item in await SkillRepository(db).get_enabled_by_owner(current_user.id)
    }
    required_skills = {item.name: item for item in definition.skills}
    skill_rows: list[dict[str, Any]] = []
    for name, requirement in required_skills.items():
        skill_id = request.skills.get(name)
        if skill_id is not None:
            skill = available_skills.get(skill_id)
            if skill is None or skill.name != name:
                raise HTTPException(422, detail=f"Invalid skill binding: {name}")
        skill_rows.append(
            {
                "requirement_name": name,
                "source": requirement.source,
                "source_ref": requirement.ref,
                "skill_id": skill_id,
                "resolved_commit": getattr(
                    existing_skill_bindings.get(name), "resolved_commit", None
                ),
                "content_hash": getattr(
                    existing_skill_bindings.get(name), "content_hash", None
                ),
            }
        )

    mcp_repository = McpServerRepository(db)
    connector_rows: list[dict[str, Any]] = []
    for catalog_id in definition.connectors:
        server_id = request.connectors.get(catalog_id)
        if server_id is not None:
            server = await mcp_repository.get_by_id_readable(
                server_id, user_id=current_user.id
            )
            if (
                server is None
                or not server.is_active
                or server.catalog_id != catalog_id
            ):
                raise HTTPException(
                    422, detail=f"Invalid connector binding: {catalog_id}"
                )
        connector_rows.append({"catalog_id": catalog_id, "mcp_server_id": server_id})
    await repository.replace_bindings(
        profile.id, skills=skill_rows, connectors=connector_rows
    )
    await repository.update(profile, {"llm_id": request.llm_id})
    updated = await _definition_or_404(agent, db, current_user, agent_ref)
    return updated.public_dict()


@router.post("/{agent_ref}/install-skills")
async def install_agent_skills(
    agent_ref: str,
    request: InstallSkillsRequest,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    agent: Annotated["BaseAgent", Depends(get_agent)],
) -> dict[str, Any]:
    if not request.confirmed:
        raise HTTPException(
            400, detail="Explicit installation confirmation is required"
        )
    definition = await _definition_or_404(agent, db, current_user, agent_ref)
    github_requirements = [item for item in definition.skills if item.source]
    unsupported = [item.name for item in definition.skills if not item.source]
    if unsupported:
        raise HTTPException(
            422,
            detail={
                "message": "Some skills have no install source",
                "skills": unsupported,
            },
        )
    repository = AgentProfileRepository(db)
    if definition.source == "builtin":
        profile = await repository.ensure_builtin_override(
            current_user.id, definition.ref
        )
    else:
        assert definition.profile_id is not None
        profile = await repository.get_for_owner(definition.profile_id, current_user.id)
        if profile is None:
            raise _not_found()
    resolved = await SandboxManager.get_cached_or_db(
        user_id=current_user.id, session=db
    )
    sandbox = SandboxRuntimeFactory.build(resolved.provider, resolved.sandbox)
    service = SkillsService(db)
    installed: list[dict[str, Any]] = []
    binding_by_name = {
        item.requirement_name: item
        for item in await repository.skill_bindings(profile.id)
    }
    try:
        for requirement in github_requirements:
            result = await install_github_skill(
                service,
                owner_id=current_user.id,
                requirement_name=requirement.name,
                source=requirement.source or "",
                ref=requirement.ref,
                sandbox=sandbox,
            )
            binding = binding_by_name.get(requirement.name)
            if binding is None:
                from giga_agent.models.agent import AgentSkillBinding

                binding = AgentSkillBinding(
                    profile_id=profile.id,
                    requirement_name=requirement.name,
                    source=requirement.source,
                    source_ref=requirement.ref,
                )
                db.add(binding)
            binding.skill_id = result.skill.id
            binding.resolved_commit = result.resolved_commit
            binding.content_hash = result.content_hash
            installed.append(
                {
                    "name": requirement.name,
                    "skill_id": result.skill.id,
                    "resolved_commit": result.resolved_commit,
                    "content_hash": result.content_hash,
                }
            )
        await db.commit()
    except SkillInstallError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    return {"installed": installed}
