from uuid import UUID, uuid5

import httpx
from jwt.exceptions import ExpiredSignatureError, PyJWTError
from langgraph_sdk import Auth
from langgraph_sdk import get_client as get_langgraph_client

from giga_agent.conf import get_settings
from giga_agent.core.db import get_session_factory
from giga_agent.models.users import UserRepository
from giga_agent.modules.auth import security

# The "Auth" object is a container that LangGraph will use to mark our authentication function
auth = Auth()


# The `authenticate` decorator tells LangGraph to call this function as middleware
# for every request. This will determine whether the request is allowed or not
@auth.authenticate
async def get_current_user(authorization: str | None) -> Auth.types.MinimalUserDict:
    """Check if the user's token is valid."""
    if not authorization:
        raise Auth.exceptions.HTTPException(
            status_code=401, detail="Could not validate credentials"
        )
    if isinstance(authorization, dict):
        authorization = authorization["authorization"]
    try:
        scheme, token = authorization.split()
    except ValueError:
        raise Auth.exceptions.HTTPException(
            status_code=401, detail="Could not validate credentials"
        )

    if scheme.lower() != "bearer":
        raise Auth.exceptions.HTTPException(
            status_code=401, detail="Could not validate credentials"
        )

    try:
        user_id = security.get_user_id_from_token(token)
    except ExpiredSignatureError:
        raise Auth.exceptions.HTTPException(status_code=401, detail="Token expired")
    except PyJWTError:
        raise Auth.exceptions.HTTPException(
            status_code=401, detail="Could not validate credentials"
        )
    except ValueError:
        raise Auth.exceptions.HTTPException(
            status_code=401, detail="Could not validate credentials"
        )

    factory = await get_session_factory()
    async with factory() as session:
        # Cache-first with DB fallback.
        user = await UserRepository.get_cached_or_db(user_id, session=session)

    if user is None:
        raise Auth.exceptions.HTTPException(
            status_code=401, detail="Could not validate credentials"
        )
    if not user.is_active:
        raise Auth.exceptions.HTTPException(status_code=401, detail="Inactive user")
    return {
        "identity": str(user.id),
        # "display_name": "Jane Doe",
        # "permissions": ["read", "write"],
        "token": token,
        "is_authenticated": True,
    }


@auth.on.threads.create
async def inject_team_id(ctx, value):
    """Inject team_id into thread metadata."""
    if "metadata" not in value or value["metadata"] is None:
        value["metadata"] = {}
    if isinstance(ctx.user, dict):
        value["metadata"]["user_id"] = ctx.user["identity"]
    else:
        value["metadata"]["user_id"] = ctx.user.identity
    return value  # Return modified value


@auth.on
async def add_owner(
    ctx: Auth.types.AuthContext,  # Contains info about the current user
    value: dict,  # The resource being created/accessed
):
    filters = {
        "user_id": (
            ctx.user["identity"] if isinstance(ctx.user, dict) else ctx.user.identity
        )
    }
    # value["metadata"] может ПРИСУТСТВОВАТЬ и быть None (aegra строит value через
    # RunCreate.model_dump(), где metadata по умолчанию None) — setdefault такой
    # случай не покрывает и падал бы на None.update(...). Обрабатываем None явно,
    # как это уже делает inject_team_id выше.
    metadata = value.get("metadata")
    if metadata is None:
        metadata = {}
        value["metadata"] = metadata
    metadata.update(filters)

    # Only let users see their own resources
    return filters


# Графы, к которым применяется лимит активных тредов. Обычный giga_agent и его
# experimental-обёртка лимитируются РАЗДЕЛЬНО — каждый своим бакетом (счёт busy
# тредов по своему graph_id). Телеграм-каналы (giga_agent_channel) и сабагенты
# со своими graph_id не ограничиваются.
LIMITED_GRAPH_IDS = ("giga_agent", "giga_agent_experimental")
# Системные дефолтные ассистенты получают детерминированный id
# uuid5(NAMESPACE_GRAPH, graph_id) — константа из langgraph_api.graph.
# Сервер конвертирует graph_id в этот id ещё до auth-хендлера, а через
# self-вызов API системный ассистент не виден (owner-фильтр add_owner
# отсекает ассистентов без user_id в metadata) — поэтому сверяем локально.
NAMESPACE_GRAPH = UUID("6ba7b821-9dad-11d1-80b4-00c04fd430c8")
_LIMITED_ASSISTANT_IDS = {
    str(uuid5(NAMESPACE_GRAPH, gid)): gid for gid in LIMITED_GRAPH_IDS
}
# Кэш assistant_id -> graph_id для кастомных (не системных) ассистентов:
# graph_id ассистента не меняется после создания, кэш не инвалидируем.
_assistant_graph_ids: dict[str, str] = {}
# Защита от распухания кэша мусорными id (резолв успешен только для
# реально существующих ассистентов, так что это просто страховка).
_ASSISTANT_CACHE_MAX = 4096


async def _resolve_graph_id(assistant_id: str, token: str) -> str | None:
    """Resolve assistant_id -> graph_id via self-call to the langgraph API.

    Возвращает None, если ассистент не найден/не виден пользователю или
    API недоступен; такие ответы не кэшируем, чтобы временная ошибка не
    залипала.
    """
    cached = _assistant_graph_ids.get(assistant_id)
    if cached is not None:
        return cached
    settings = get_settings()
    client = get_langgraph_client(
        url=settings.giga_agent_langgraph_api_url,
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        assistant = await client.assistants.get(assistant_id)
    except httpx.HTTPError:
        return None
    finally:
        await client.aclose()
    graph_id = assistant.get("graph_id")
    if graph_id:
        if len(_assistant_graph_ids) >= _ASSISTANT_CACHE_MAX:
            _assistant_graph_ids.clear()
        _assistant_graph_ids[assistant_id] = graph_id
    return graph_id


# Машиночитаемый маркер: фронт (ChatError.tsx) ищет эту подстроку в тексте
# ошибки, чтобы показать дружелюбное сообщение.
TOO_MANY_ACTIVE_THREADS_MARKER = "TOO_MANY_ACTIVE_THREADS"


def _experimental_inner_run(value: dict) -> bool:
    """True, если это скрытый inner-ран experimental-обёртки.

    experimental-режим лимитируется по ВНЕШНЕМУ графу (giga_agent_experimental),
    а не по этому inner-giga_agent-рану, который обёртка запускает сама в скрытом
    треде (иначе один ход пользователя стоил бы двух «активных тредов»). Поэтому
    inner-ран выводим из-под лимита: kickoff/interrupt_node помечают его флагом
    в configurable (см. experimental/graph.py). Флаг durable по построению — он
    часть payload'а рана.
    """
    config = value.get("config")
    if not isinstance(config, dict):
        return False
    configurable = config.get("configurable")
    if not isinstance(configurable, dict):
        return False
    return bool(configurable.get("experimental_inner"))


@auth.on.threads.create_run
async def limit_active_threads(ctx: Auth.types.AuthContext, value: dict):
    """Reject run creation when the user has too many busy threads.

    Количество активных тредов считаем по API самого langgraph-сервера
    (self-вызов с токеном пользователя): search вернёт только треды этого
    пользователя благодаря owner-фильтрам add_owner. Лимитируемые графы
    (`LIMITED_GRAPH_IDS`) считаются РАЗДЕЛЬНО — каждый по своему `graph_id`.
    """
    settings = get_settings()
    limit = settings.giga_agent_max_active_threads_per_user
    # Скрытый inner-ран experimental-обёртки не лимитируем — режим ограничивается
    # по внешнему графу giga_agent_experimental (см. _experimental_inner_run).
    if limit > 0 and not _experimental_inner_run(value):
        token = ctx.user["token"] if isinstance(ctx.user, dict) else ctx.user.token
        assistant_id = str(value.get("assistant_id"))
        graph_id = _LIMITED_ASSISTANT_IDS.get(assistant_id)
        if graph_id is None and assistant_id in LIMITED_GRAPH_IDS:
            graph_id = assistant_id
        if graph_id is None:
            # Кастомный ассистент мог быть создан поверх лимитируемого графа.
            graph_id = await _resolve_graph_id(assistant_id, token)
        if graph_id in LIMITED_GRAPH_IDS:
            thread_id = str(value.get("thread_id"))
            client = get_langgraph_client(
                url=settings.giga_agent_langgraph_api_url,
                headers={"Authorization": f"Bearer {token}"},
            )
            try:
                threads = await client.threads.search(
                    status="busy",
                    metadata={"graph_id": graph_id},
                    # Бакеты раздельные (по graph_id), но giga_agent-бакет может
                    # содержать скрытые inner-треды experimental-обёртки — их из
                    # счёта исключаем (лимитируется внешний ран). Берём запас,
                    # чтобы такие треды не вытеснили реальные из выборки.
                    limit=limit * 2 + 1,
                )
            finally:
                await client.aclose()
            # Ретрай/double-text в уже занятый тред — не двойной счёт; скрытые
            # inner-треды experimental-обёртки (experimental_inner) не считаем.
            active = sum(
                1
                for t in threads
                if t["thread_id"] != thread_id
                and not (t.get("metadata") or {}).get("experimental_inner")
            )
            if active >= limit:
                raise Auth.exceptions.HTTPException(
                    # 409: JS SDK ретраит 429, а 409 отдаёт сразу.
                    status_code=409,
                    detail=(
                        f"{TOO_MANY_ACTIVE_THREADS_MARKER}: Слишком много "
                        "активных тредов — дождитесь завершения или "
                        "остановите ненужные."
                    ),
                )
    # Специфичный хендлер затеняет generic @auth.on — сохраняем owner-логику.
    return await add_owner(ctx, value)
