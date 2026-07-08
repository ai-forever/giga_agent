"""API router for agent runtime metadata."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, Literal

from cashews import cache
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from giga_agent.core.deps import get_agent
from giga_agent.core.module import SecretMetadata, collect_module_secrets
from giga_agent.models.users import UserShort
from giga_agent.modules.auth.api import get_current_active_user

if TYPE_CHECKING:
    from giga_agent.core.agent.base import BaseAgent

router = APIRouter(prefix="/agent", tags=["agent"])


class SecretMetadataResponse(BaseModel):
    name: str
    description: str | None = None
    type: Literal["pass", "text", "llm_id"] = "pass"


class ModuleResponse(BaseModel):
    id: str
    label: str
    description: str
    icon: str


@router.get("/secrets", response_model=list[SecretMetadataResponse])
async def get_agent_secrets(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    agent: Annotated["BaseAgent", Depends(get_agent)],
) -> list[SecretMetadata]:
    _ = current_user
    return collect_module_secrets(agent.all_modules)


@cache(ttl="30s", key="modules:user:{user.id}")
async def _modules_for_user(
    agent: "BaseAgent", user: UserShort
) -> list[ModuleResponse]:
    result: list[ModuleResponse] = []
    for module in agent.all_modules:
        if not module.label:
            continue
        if not await module.is_enabled(user):
            continue
        result.append(
            ModuleResponse(
                id=module.id,
                label=module.label,
                description=module.description,
                icon=module.icon,
            )
        )
    return result


@router.get("/modules", response_model=list[ModuleResponse])
async def get_agent_modules(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    agent: Annotated["BaseAgent", Depends(get_agent)],
) -> list[ModuleResponse]:
    return await _modules_for_user(agent, current_user)


class ModuleManualField(BaseModel):
    key: str
    label: str
    secret: bool = True
    placeholder: str | None = None


class ModuleCatalogEntry(BaseModel):
    """A connectable native module, normalized for the unified connectors grid."""

    kind: Literal["module"] = "module"
    module_id: str
    name: str
    description: str | None = None
    icon: str | None = None  # external URL (provider favicon)
    categories: list[str] = []
    provider_key: str
    auth_kind: str  # oauth2 | manual_token | both
    manual_fields: list[ModuleManualField] = []
    status: str  # connected | not_connected | needs_reauth
    enabled: bool


class ConnectorsCatalogResponse(BaseModel):
    """Unified connectors directory: MCP server templates + native modules."""

    mcp: list[Any]
    modules: list[ModuleCatalogEntry]


async def _module_catalog_entries(
    agent: "BaseAgent", user: UserShort
) -> list[ModuleCatalogEntry]:
    from giga_agent.core.agent.base import _disabled_module_ids

    disabled = _disabled_module_ids(None, user)
    entries: list[ModuleCatalogEntry] = []
    for module in agent.all_modules:
        if not module.label:
            continue
        providers = module.get_providers()
        if not providers:
            continue
        # The first declared provider drives the connect affordance.
        provider = providers[0]
        info = provider.info()
        st = await provider.status(user_id=user.id)
        entries.append(
            ModuleCatalogEntry(
                module_id=module.id,
                name=module.label,
                description=module.description or None,
                icon=info.icon,
                categories=module.categories,
                provider_key=info.key,
                auth_kind=info.auth_kind,
                manual_fields=[
                    ModuleManualField(
                        key=f.key,
                        label=f.label,
                        secret=f.secret,
                        placeholder=f.placeholder,
                    )
                    for f in info.manual_fields
                ],
                status=st.status,
                enabled=module.id not in disabled,
            )
        )
    return entries


class ToolInfoResponse(BaseModel):
    name: str
    description: str | None = None


class ModuleToolsResponse(BaseModel):
    tools: list[ToolInfoResponse]


@router.get(
    "/connectors/modules/{module_id}/tools",
    response_model=ModuleToolsResponse,
)
async def get_module_tools(
    module_id: str,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    agent: Annotated["BaseAgent", Depends(get_agent)],
) -> ModuleToolsResponse:
    """Список инструментов, которые подключённый нативный модуль отдаёт агенту.

    Аналог ``/mcp/servers/tools-by-name/{key}`` для MCP-серверов: раскрывает,
    какие тулы появятся у агента после подключения модуля. Тулы берутся из
    :meth:`BaseModule.get_tool_sources` (ленивые модули оборачивают их в
    ``ModuleToolSource``), поэтому список совпадает с тем, что видит модель
    через ``connector_get_info``.
    """
    module = next((m for m in agent.all_modules if m.id == module_id), None)
    if module is None:
        raise HTTPException(status_code=404, detail="module not found")

    sources = await module.get_tool_sources(current_user, agent)
    tools: list[ToolInfoResponse] = []
    seen: set[str] = set()
    for source in sources:
        for spec in await source.list_tools(user_id=current_user.id):
            if spec.name in seen:
                continue
            seen.add(spec.name)
            tools.append(
                ToolInfoResponse(name=spec.name, description=spec.description or None)
            )
    return ModuleToolsResponse(tools=tools)


@router.get("/connectors/catalog", response_model=ConnectorsCatalogResponse)
async def get_connectors_catalog(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    agent: Annotated["BaseAgent", Depends(get_agent)],
) -> ConnectorsCatalogResponse:
    """Unified directory for the «Add connector» UI.

    Combines curated MCP server templates with connectable native modules
    (those declaring an integrations provider), so the frontend renders both in
    one grid. MCP entries connect via the MCP server flow; module entries via
    the integrations OAuth/token flow.
    """
    from giga_agent.modules.mcp.catalog import visible_catalog

    return ConnectorsCatalogResponse(
        mcp=visible_catalog(),
        modules=await _module_catalog_entries(agent, current_user),
    )
