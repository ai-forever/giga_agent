import uuid
from collections import defaultdict
from datetime import timedelta
from typing import Annotated, Awaitable, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit

from cashews import cache
from jwt.exceptions import ExpiredSignatureError, PyJWTError
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.conf import get_settings
from giga_agent.core.db import get_session
from giga_agent.core.module import collect_module_secrets
from giga_agent.models.connector import ConnectorRepository
from giga_agent.models.embedding import EmbeddingRepository
from giga_agent.models.group import GroupRepository
from giga_agent.models.image_generator import ImageGeneratorRepository
from giga_agent.models.llm import LLMRepository
from giga_agent.models.rag import RagCollectionsRepository
from giga_agent.models.sandbox import (
    SandboxProviderRepository,
    SandboxProviderSnapshot,
    SandboxRepository,
    SandboxSnapshot,
)
from giga_agent.models.search_engine import SearchEngineRepository
from giga_agent.models.resource_permission import (
    PermissionGrantItem,
    ResourcePermission,
    ResourcePermissionRepository,
)
from giga_agent.modules.auth import security
from giga_agent.modules.auth.security import ACCESS_TOKEN_EXPIRE_MINUTES
from giga_agent.modules.auth.login_throttle import (
    check_login_throttle,
    get_client_ip,
    record_login_failure,
    reset_login,
)
from giga_agent.sandbox.access import (
    SANDBOX_ACCESS_QUERY_PARAM,
    SANDBOX_ACCESS_TTL_SEC,
    is_sandbox_access_token_valid,
    sandbox_access_cookie_name,
)
from giga_agent.core.events import event_bus
from giga_agent.modules.auth.events import UserCreatedEvent, UserEmbeddingChangedEvent
from giga_agent.models.users import (
    User,
    UserShort,
    UserRepository,
    UserResponse,
    UserSelfResponse,
    UserCreate,
    UserUpdate,
    AdminUserUpdate,
)
from giga_agent.models.file import FileRepository, FileStorageRef
from giga_agent.modules.skills.service import SkillsService
from giga_agent.sandbox.cleanup_tasks import cleanup_storage_files_best_effort
from giga_agent.sandbox.manager import SandboxManager

router = APIRouter(tags=["auth"])

AUTH_COOKIE_NAME = "access_token"
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)


def _app_session_cookie_domain() -> str | None:
    """Domain for the app session cookie.

    In cross-domain sandbox mode (``GIGA_AGENT_SANDBOX_PORT_REDIRECT_BASE``
    set) the app and the sandboxes are on different domains, so the session
    cookie must NOT be scoped to ``giga_agent_public_base_domain`` (that is the
    sandbox domain) — the browser would reject it on the app host. Default to a
    host-only cookie (``None``); an explicit ``GIGA_AGENT_APP_COOKIE_DOMAIN``
    overrides. In the normal (same-domain) mode, keep the previous behaviour:
    scope the cookie to ``giga_agent_public_base_domain`` so it is shared with
    the ``*-sandbox-*`` subdomains.
    """
    settings = get_settings()
    if settings.giga_agent_app_cookie_domain:
        return settings.giga_agent_app_cookie_domain
    if settings.giga_agent_sandbox_port_redirect_base:
        return None
    return settings.giga_agent_public_base_domain


# ============ Dependency для получения репозитория ============


async def get_user_repository(
    db: Annotated[AsyncSession, Depends(get_session)],
) -> UserRepository:
    return UserRepository(db)


# ============ Dependencies для получения текущего пользователя ============


async def get_current_user(
    request: Request,
    token: Annotated[str | None, Depends(oauth2_scheme)],
    user_repo: Annotated[UserRepository, Depends(get_user_repository)],
) -> UserShort:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    token_expired_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token expired",
        headers={"WWW-Authenticate": "Bearer"},
    )
    raw_token = token or request.cookies.get(AUTH_COOKIE_NAME)
    if not raw_token:
        raise credentials_exception

    if raw_token.lower().startswith("bearer "):
        raw_token = raw_token[7:].strip()

    try:
        user_id = security.get_user_id_from_token(raw_token)
    except ExpiredSignatureError:
        raise token_expired_exception
    except PyJWTError:
        raise credentials_exception
    except ValueError:  # Invalid UUID string
        raise credentials_exception

    user = await user_repo.get_by_id(user_id, use_cache=True)
    if user is None:
        raise credentials_exception
    return user


async def get_current_active_user(
    current_user: Annotated[UserShort, Depends(get_current_user)],
) -> UserShort:
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


# ============ Pydantic схемы для API ============


class Token(BaseModel):
    access_token: str
    token_type: str


async def _get_user_model_by_id(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> User:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return user


def _invalid_reference_error(field_name: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=(
            f"Invalid value for {field_name}: record must exist, be owned by user "
            "or readable by user, and be active"
        ),
    )


def require_superuser(current_user: UserShort) -> None:
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )


def require_role(current_user: UserShort, minimum: str) -> None:
    """Проверка роли по иерархии member < admin < owner."""
    from giga_agent.models.users import role_at_least

    if not role_at_least(current_user.role, minimum):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )


def _collect_runtime_grant_targets_from_user_model(
    user_model: User,
) -> set[tuple[str, uuid.UUID]]:
    targets: set[tuple[str, uuid.UUID]] = set()
    llm_ids = {item for item in [user_model.llm_id, user_model.fast_llm_id] if item}
    for llm_id in llm_ids:
        targets.add(("llm", llm_id))

    runtime_refs: list[tuple[str, uuid.UUID | None]] = [
        ("embedding", user_model.embedding_id),
        ("image_generator", user_model.image_generator_id),
        ("search_engine", user_model.search_engine_id),
        ("sandbox", user_model.sandbox_provider_id),
    ]
    for resource_type, resource_id in runtime_refs:
        if resource_id is not None:
            targets.add((resource_type, resource_id))
    return targets


async def _collect_runtime_grant_targets_from_module_secrets(
    *,
    request: Request,
    secrets: dict,
) -> set[tuple[str, uuid.UUID]]:
    agent = getattr(request.app.state, "agent", None)
    if agent is None:
        return set()

    targets: set[tuple[str, uuid.UUID]] = set()
    for secret_meta in collect_module_secrets(agent.all_modules):
        secret_name = secret_meta["name"]
        secret_type = secret_meta.get("type") or "pass"
        if secret_type != "llm_id":
            continue

        raw_value = secrets.get(secret_name)
        if raw_value is None:
            continue
        value = str(raw_value).strip()
        if not value:
            continue
        try:
            llm_id = uuid.UUID(value)
        except ValueError:
            continue
        targets.add(("llm", llm_id))

    return targets


async def _validate(
    db: AsyncSession,
    user_id: uuid.UUID,
    resource_type: str,
    resource_id: uuid.UUID,
    field_name: str,
    loader: Callable[[uuid.UUID], Awaitable[object | None]],
) -> None:
    resource = await loader(resource_id)
    if resource is None:
        raise _invalid_reference_error(field_name)

    owner_id = getattr(resource, "owner_id", None)
    is_active = getattr(resource, "is_active", False)
    if owner_id is None or not is_active:
        raise _invalid_reference_error(field_name)

    if owner_id == user_id:
        return

    has_read_access = await ResourcePermissionRepository(db).has_access(
        user_id=user_id,
        resource_type=resource_type,
        resource_id=resource_id,
        permission="read",
    )
    if not has_read_access:
        raise _invalid_reference_error(field_name)


async def _validate_llm_id(
    db: AsyncSession,
    user_id: uuid.UUID,
    llm_id: uuid.UUID,
    field_name: str = "llm_id",
) -> None:
    await _validate(
        db=db,
        user_id=user_id,
        resource_type="llm",
        resource_id=llm_id,
        field_name=field_name,
        loader=lambda resource_id: LLMRepository.get_cached_or_db(resource_id, session=db),
    )


async def _validate_embedding_id(
    db: AsyncSession,
    user_id: uuid.UUID,
    embedding_id: uuid.UUID,
) -> None:
    await _validate(
        db=db,
        user_id=user_id,
        resource_type="embedding",
        resource_id=embedding_id,
        field_name="embedding_id",
        loader=lambda resource_id: EmbeddingRepository.get_cached_or_db(
            resource_id,
            session=db,
        ),
    )


async def _validate_image_generator_id(
    db: AsyncSession,
    user_id: uuid.UUID,
    image_generator_id: uuid.UUID,
) -> None:
    await _validate(
        db=db,
        user_id=user_id,
        resource_type="image_generator",
        resource_id=image_generator_id,
        field_name="image_generator_id",
        loader=lambda resource_id: ImageGeneratorRepository.get_cached_or_db(
            resource_id,
            session=db,
        ),
    )


async def _validate_search_engine_id(
    db: AsyncSession,
    user_id: uuid.UUID,
    search_engine_id: uuid.UUID,
) -> None:
    await _validate(
        db=db,
        user_id=user_id,
        resource_type="search_engine",
        resource_id=search_engine_id,
        field_name="search_engine_id",
        loader=lambda resource_id: SearchEngineRepository.get_cached_or_db(
            resource_id,
            session=db,
        ),
    )


async def _validate_sandbox_provider_id(
    db: AsyncSession,
    user_id: uuid.UUID,
    sandbox_provider_id: uuid.UUID,
) -> None:
    await _validate(
        db=db,
        user_id=user_id,
        resource_type="sandbox",
        resource_id=sandbox_provider_id,
        field_name="sandbox_provider_id",
        loader=lambda resource_id: SandboxProviderRepository(db).get_by_id(resource_id),
    )


async def _validate_llm_secret_references(
    *,
    request: Request,
    db: AsyncSession,
    user_id: uuid.UUID,
    merged_secrets: dict,
) -> None:
    agent = getattr(request.app.state, "agent", None)
    if agent is None:
        return

    for secret_meta in collect_module_secrets(agent.all_modules):
        if secret_meta["type"] != "llm_id":
            continue

        secret_name = secret_meta["name"]
        raw_value = merged_secrets.get(secret_name)
        if raw_value is None:
            continue

        value = str(raw_value).strip()
        if not value:
            continue

        try:
            llm_id = uuid.UUID(value)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Invalid value for secrets.{secret_name}: expected UUID of an "
                    "accessible active LLM"
                ),
            )

        await _validate_llm_id(
            db,
            user_id,
            llm_id,
            field_name=f"secrets.{secret_name}",
        )


def _mask_user_self_secrets(
    request: Request,
    secrets: dict | None,
) -> dict | None:
    if not secrets:
        return secrets

    agent = getattr(request.app.state, "agent", None)
    if agent is None:
        return secrets

    pass_secret_names = {
        secret_meta["name"]
        for secret_meta in collect_module_secrets(agent.all_modules)
        if (secret_meta.get("type") or "pass") == "pass"
    }
    if not pass_secret_names:
        return secrets

    masked_secrets = dict(secrets)
    for secret_name in pass_secret_names:
        if secret_name not in masked_secrets:
            continue

        raw_value = masked_secrets.get(secret_name)
        value = ""
        if raw_value is not None:
            value = str(raw_value).strip()
        masked_secrets[secret_name] = {"filled": bool(value)}
    return masked_secrets


def _serialize_user_self_response(
    request: Request,
    user: object,
) -> UserSelfResponse:
    payload = UserSelfResponse.model_validate(user).model_dump()
    payload["secrets"] = _mask_user_self_secrets(request, payload.get("secrets"))
    return UserSelfResponse.model_validate(payload)


async def _delete_user_related_resources(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    file_refs: list[FileStorageRef],
):
    _ = file_refs
    await FileRepository(db).delete_by_owner(user_id)

    rag_repo = RagCollectionsRepository(db)
    for collection in await rag_repo.list_by_owner(user_id):
        await rag_repo.delete(owner_id=user_id, collection_id=collection.id)

    sandbox_repo = SandboxRepository(db)
    sandbox_manager = SandboxManager(db)
    for sandbox in await sandbox_repo.get_by_owner(user_id):
        try:
            await sandbox_manager.stop(sandbox.id)
        except Exception:
            pass
        await sandbox_repo.delete(sandbox)

    provider_repo = SandboxProviderRepository(db)
    for provider in await provider_repo.get_by_owner(user_id):
        await provider_repo.delete(provider)

    search_repo = SearchEngineRepository(db)
    for engine in await search_repo.get_by_owner(user_id):
        await search_repo.delete(engine)

    image_repo = ImageGeneratorRepository(db)
    for generator in await image_repo.get_by_owner(user_id):
        await image_repo.delete(generator)

    llm_repo = LLMRepository(db)
    for llm in await llm_repo.get_by_owner(user_id):
        await llm_repo.delete(llm)

    embedding_repo = EmbeddingRepository(db)
    for embedding in await embedding_repo.get_by_owner(user_id):
        await embedding_repo.delete(embedding)

    connector_repo = ConnectorRepository(db)
    for connector in await connector_repo.get_by_owner(user_id):
        await connector_repo.delete(connector)

    group_repo = GroupRepository(db)
    for group in await group_repo.list_all():
        if group.owner_id == user_id:
            await group_repo.delete(group)

    await db.execute(
        delete(ResourcePermission)
        .where(ResourcePermission.owner_type == "user")
        .where(ResourcePermission.owner_id == str(user_id))
    )
    await db.commit()
    await UserRepository.invalidate_cache(user_id)
    return


async def _build_user_storage_cleanup_batches(
    db: AsyncSession,
    user_id: uuid.UUID,
):
    file_refs = await FileRepository(db).list_storage_refs_by_owner(user_id)
    refs_by_provider: dict[uuid.UUID, list[FileStorageRef]] = defaultdict(list)
    for ref in file_refs:
        refs_by_provider[ref.provider_id].append(ref)

    provider_repo = SandboxProviderRepository(db)
    sandbox_repo = SandboxRepository(db)
    batches: list[
        tuple[list[FileStorageRef], SandboxProviderSnapshot, dict[str, SandboxSnapshot]]
    ] = []

    for provider_id, provider_refs in refs_by_provider.items():
        provider = await provider_repo.get_by_id(provider_id)
        if provider is None:
            continue

        provider_snapshot = SandboxProviderSnapshot(
            id=provider.id,
            owner_id=provider.owner_id,
            type=provider.type,
            name=provider.name,
            settings=provider.settings or {},
            idle_timeout=provider.idle_timeout,
            is_active=provider.is_active,
            updated_at=provider.updated_at,
        )
        sandbox_snapshots_by_owner: dict[str, SandboxSnapshot] = {}
        for owner_id in {item.owner_id for item in provider_refs}:
            sandbox = await sandbox_repo.get_by_owner_and_provider(owner_id, provider_id)
            if sandbox is None:
                continue
            pair = SandboxRepository.to_pair_snapshot(provider, sandbox)
            sandbox_snapshots_by_owner[str(owner_id)] = pair.sandbox

        batches.append((provider_refs, provider_snapshot, sandbox_snapshots_by_owner))

    return file_refs, batches


# ============ Endpoints ============


@router.post("/token", response_model=Token)
async def login_for_access_token(
    request: Request,
    response: Response,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    user_repo: Annotated[UserRepository, Depends(get_user_repository)],
):
    # Идентификатор для ключа троттла (login_throttle нормализует его внутри: strip+lower).
    # Для поиска в БД используем form_data.username как есть — регистр email не трогаем,
    # чтобы не сломать вход аккаунтам со смешанным регистром.
    username = form_data.username
    client_ip = get_client_ip(request)
    # Проверяем троттл ДО bcrypt: экономим CPU и не даём тайминг-сигнал.
    await check_login_throttle(username, client_ip)

    user = await user_repo.get_by_email(username)
    if not user:
        # Аккаунта нет: всё равно прогоняем bcrypt против фиктивного хэша, чтобы время
        # ответа не выдавало существование email. Неудачу НЕ записываем — иначе перебор
        # случайных email засадит Redis мусорными ключами (cache-fill).
        security.verify_password(form_data.password, security._DUMMY_PASSWORD_HASH)
        ok = False
    else:
        ok = security.verify_password(form_data.password, user.hashed_password)

    if not ok:
        if user:
            await record_login_failure(username, client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Успех — сбрасываем счётчики неудач.
    await reset_login(username, client_ip)
    access_token_expires = (
        timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        if ACCESS_TOKEN_EXPIRE_MINUTES
        else None
    )

    # Include user_id in token as requested
    access_token = security.create_access_token(
        data={"sub": user.email, "user_id": str(user.id)},
        expires_delta=access_token_expires,
    )
    cookie_domain = _app_session_cookie_domain()
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=access_token,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
        domain=cookie_domain,
    )
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response):
    cookie_domain = _app_session_cookie_domain()
    response.delete_cookie(
        key=AUTH_COOKIE_NAME, path="/", domain=cookie_domain,
    )


def _sandbox_grant_redirect_target(request: Request) -> str:
    """Path to land on after the capability-cookie exchange.

    Uses the original client URI (forwarded by nginx as ``X-Original-URI``) so
    the user returns to the page they actually requested — e.g. ``/snake.html``
    — instead of the sandbox root. The one-time ``__sbx`` token is stripped so
    the redirect doesn't re-trigger the grant loop.

    Only same-origin, root-relative paths are honored (open-redirect guard);
    anything with a scheme/host or a protocol-relative ``//`` prefix falls back
    to ``/``.
    """
    original = request.headers.get("x-original-uri") or ""
    if not original.startswith("/") or original.startswith(("//", "/\\")):
        return "/"

    parts = urlsplit(original)
    if parts.scheme or parts.netloc:
        return "/"

    path = parts.path or "/"
    query = urlencode(
        [
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if key != SANDBOX_ACCESS_QUERY_PARAM
        ]
    )
    return f"{path}?{query}" if query else path


def _parse_sandbox_id_hex(sandbox_id_hex: str) -> uuid.UUID:
    if len(sandbox_id_hex) != 32:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    try:
        return uuid.UUID(hex=sandbox_id_hex)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.get(
    "/sandbox-access/{sandbox_id_hex}/{port}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def verify_sandbox_access(
    sandbox_id_hex: str,
    port: int,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    """Auth_request endpoint for the sandbox wildcard subdomain.

    Grants access (204) via either path:
      * a valid, non-expired capability cookie scoped to this exact
        ``(sandbox_id, port)`` pair, or
      * the owner's main session cookie (the user owns the sandbox).

    Otherwise 401 (no/bad credentials), 403 (not owner), or 404 (invalid id /
    sandbox missing).
    """
    sandbox_id = _parse_sandbox_id_hex(sandbox_id_hex)

    # 1. Capability token (port-scoped, time-limited) — preferred, no DB hit.
    cap_token = request.cookies.get(sandbox_access_cookie_name(sandbox_id_hex))
    if await is_sandbox_access_token_valid(sandbox_id_hex, port, cap_token):
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # 2. Fall back to the owner's main session cookie.
    raw_token = request.cookies.get(AUTH_COOKIE_NAME)
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    if raw_token.lower().startswith("bearer "):
        raw_token = raw_token[7:].strip()
    try:
        user_id = security.get_user_id_from_token(raw_token)
    except (ExpiredSignatureError, PyJWTError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    owner_id = await SandboxRepository(db).get_owner_id_by_sandbox_cached(sandbox_id)
    if owner_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if owner_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/sandbox-grant/{sandbox_id_hex}/{port}")
async def grant_sandbox_access(
    sandbox_id_hex: str,
    port: int,
    request: Request,
) -> Response:
    """Exchange a capability token from the query string for a host-only cookie.

    Validates ``?{SANDBOX_ACCESS_QUERY_PARAM}=<token>`` against Redis for this
    exact ``(sandbox_id, port)`` pair, sets a per-sandbox host-only cookie, and
    302-redirects back to the originally requested path (``X-Original-URI`` from
    nginx, ``__sbx`` stripped) — falling back to ``/`` — so the token disappears
    from the address bar and is not leaked via Referer. The cookie is then
    validated on every request by the auth_request endpoint.
    """
    _parse_sandbox_id_hex(sandbox_id_hex)

    token = request.query_params.get(SANDBOX_ACCESS_QUERY_PARAM)
    if not await is_sandbox_access_token_valid(sandbox_id_hex, port, token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired sandbox access token",
        )

    secure = request.headers.get("x-forwarded-proto", "https") == "https"
    redirect_target = _sandbox_grant_redirect_target(request)
    response = RedirectResponse(url=redirect_target, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key=sandbox_access_cookie_name(sandbox_id_hex),
        value=token,  # type: ignore[arg-type]
        max_age=SANDBOX_ACCESS_TTL_SEC,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
        # No domain attribute → host-only: the cookie is scoped to this exact
        # <port>-sandbox-<hex>.<domain> host and is never sent to siblings.
    )
    return response


@router.get("/users/me", response_model=UserSelfResponse)
async def read_users_me(
    request: Request,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
):
    return _serialize_user_self_response(request, current_user)


@router.get("/users", response_model=list[UserResponse])
async def list_users(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    user_repo: Annotated[UserRepository, Depends(get_user_repository)],
):
    require_superuser(current_user)
    users = await user_repo.get_all()
    return [UserRepository.to_response(user) for user in users]


@router.patch("/users/me", response_model=UserSelfResponse)
async def update_user(
    body: UserUpdate,
    request: Request,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """Частично обновить профиль текущего пользователя."""
    if not body.model_fields_set:
        return _serialize_user_self_response(request, current_user)

    user = await _get_user_model_by_id(db, current_user.id)
    old_embedding_id = user.embedding_id

    if "settings" in body.model_fields_set:
        if body.settings is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="settings must be an object when provided",
            )
        merged_settings = dict(user.settings or {})
        merged_settings.update(body.settings)
        user.settings = merged_settings

    if "secrets" in body.model_fields_set:
        if body.secrets is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="secrets must be an object when provided",
            )
        merged_secrets = dict(user.secrets or {})
        merged_secrets.update(body.secrets)
        await _validate_llm_secret_references(
            request=request,
            db=db,
            user_id=current_user.id,
            merged_secrets=merged_secrets,
        )
        user.secrets = merged_secrets

    if "llm_id" in body.model_fields_set:
        if body.llm_id is not None:
            await _validate_llm_id(db, current_user.id, body.llm_id)
        user.llm_id = body.llm_id

    if "fast_llm_id" in body.model_fields_set:
        if body.fast_llm_id is not None:
            await _validate_llm_id(
                db,
                current_user.id,
                body.fast_llm_id,
                field_name="fast_llm_id",
            )
        user.fast_llm_id = body.fast_llm_id

    if "embedding_id" in body.model_fields_set:
        if body.embedding_id is not None:
            await _validate_embedding_id(db, current_user.id, body.embedding_id)
        user.embedding_id = body.embedding_id

    if "image_generator_id" in body.model_fields_set:
        if body.image_generator_id is not None:
            await _validate_image_generator_id(
                db,
                current_user.id,
                body.image_generator_id,
            )
        user.image_generator_id = body.image_generator_id

    if "search_engine_id" in body.model_fields_set:
        if body.search_engine_id is not None:
            await _validate_search_engine_id(db, current_user.id, body.search_engine_id)
        user.search_engine_id = body.search_engine_id

    if "sandbox_provider_id" in body.model_fields_set:
        if body.sandbox_provider_id is not None:
            await _validate_sandbox_provider_id(
                db,
                current_user.id,
                body.sandbox_provider_id,
            )
        user.sandbox_provider_id = body.sandbox_provider_id
        await cache.delete_match(f"sandboxpair:owner:{current_user.id}:*")
        await SkillsService.invalidate_list_cache(current_user.id)

    await db.commit()
    await db.refresh(user)
    await UserRepository.invalidate_cache(user.id)
    if old_embedding_id != user.embedding_id:
        await event_bus.publish(
            UserEmbeddingChangedEvent(
                user_id=user.id,
                old_embedding_id=old_embedding_id,
                new_embedding_id=user.embedding_id,
            )
        )
    return _serialize_user_self_response(request, UserRepository.to_short(user))


@router.post("/users", response_model=UserResponse)
async def create_user(
    request: Request,
    user: UserCreate,
    user_repo: Annotated[UserRepository, Depends(get_user_repository)],
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    require_superuser(current_user)

    if await user_repo.exists_by_email(user.email):
        raise HTTPException(status_code=400, detail="Email already registered")

    hashed_password = security.get_password_hash(user.password)
    normalized_group_ids = list(dict.fromkeys(user.group_ids))
    group_repo = GroupRepository(db)

    if normalized_group_ids:
        existing_group_ids = set(
            await group_repo.get_existing_group_ids(normalized_group_ids)
        )
        missing_group_ids = [
            group_id
            for group_id in normalized_group_ids
            if group_id not in existing_group_ids
        ]
        if missing_group_ids:
            missing_group_ids_str = ", ".join(
                str(group_id) for group_id in missing_group_ids
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Groups not found: {missing_group_ids_str}",
            )

    # role — источник правды, если задана явно; иначе легаси-вывод из
    # is_superuser. Создать owner'а нельзя — владение только передаётся
    # (PATCH существующего пользователя самим owner'ом).
    explicit_role = "role" in user.model_fields_set
    if explicit_role and user.role not in ("admin", "member"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="role must be 'admin' or 'member' (owner is transfer-only)",
        )
    resolved_role = (
        user.role if explicit_role else ("admin" if user.is_superuser else "member")
    )

    try:
        db_user = await user_repo.create(
            email=user.email,
            hashed_password=hashed_password,
            first_name=user.first_name,
            last_name=user.last_name,
            is_active=user.is_active,
            role=resolved_role,
            commit=False,
        )

        if user.copy_owner_runtime_ids:
            owner_model = await _get_user_model_by_id(db, current_user.id)
            db_user.llm_id = owner_model.llm_id
            db_user.fast_llm_id = owner_model.fast_llm_id
            db_user.embedding_id = owner_model.embedding_id
            db_user.image_generator_id = owner_model.image_generator_id
            db_user.search_engine_id = owner_model.search_engine_id
            db_user.sandbox_provider_id = owner_model.sandbox_provider_id

            grant_targets = _collect_runtime_grant_targets_from_user_model(owner_model)

            if user.copy_owner_module_secrets:
                db_user.secrets = dict(owner_model.secrets or {})
                grant_targets.update(
                    await _collect_runtime_grant_targets_from_module_secrets(
                        request=request,
                        secrets=db_user.secrets,
                    )
                )

            if grant_targets:
                grants = [
                    PermissionGrantItem(
                        resource_type=resource_type,
                        resource_id=resource_id,
                        owner_type="user",
                        owner_id=db_user.id,
                        permission="read",
                    )
                    for resource_type, resource_id in sorted(
                        grant_targets,
                        key=lambda item: (item[0], str(item[1])),
                    )
                ]
                await ResourcePermissionRepository(db).grant_permissions(
                    items=grants,
                    no_commit=True,
                )

        for group_id in normalized_group_ids:
            await group_repo.add_users(group_id, [db_user.id], commit=False)
        await db.commit()
        await db.refresh(db_user)
    except Exception:
        await db.rollback()
        raise

    await event_bus.publish(UserCreatedEvent(user_id=db_user.id, email=db_user.email))

    return db_user


@router.patch("/users/{user_id}", response_model=UserResponse)
async def patch_user_by_id(
    user_id: uuid.UUID,
    body: AdminUserUpdate,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    user_repo: Annotated[UserRepository, Depends(get_user_repository)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    require_superuser(current_user)

    user = await _get_user_model_by_id(db, user_id)

    changes_current_user_flags = (
        ("is_active" in body.model_fields_set and body.is_active != user.is_active)
        or (
            "is_superuser" in body.model_fields_set
            and body.is_superuser != user.is_superuser
        )
        or ("role" in body.model_fields_set and body.role != user.role)
    )
    if user_id == current_user.id and changes_current_user_flags:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cannot change is_active or is_superuser for current user",
        )

    # Защита владельца: менять роль/активность owner'а может только сам owner
    # (свои флаги и так менять нельзя — правило выше). Назначить owner'ом
    # другого пользователя может тоже только текущий owner (передача владения).
    from giga_agent.models.users import (
        ROLE_OWNER,
        role_implies_superuser,
    )

    touches_protected = (
        "role" in body.model_fields_set
        or "is_active" in body.model_fields_set
        or "is_superuser" in body.model_fields_set
    )
    if touches_protected and user.role == ROLE_OWNER and current_user.role != ROLE_OWNER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the owner can modify the owner account",
        )
    if (
        "role" in body.model_fields_set
        and body.role == ROLE_OWNER
        and current_user.role != ROLE_OWNER
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the owner can transfer ownership",
        )

    if "email" in body.model_fields_set:
        if body.email is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="email must not be null",
            )
        if body.email != user.email and await user_repo.exists_by_email(body.email):
            raise HTTPException(status_code=400, detail="Email already registered")
        user.email = body.email

    if "password" in body.model_fields_set:
        password = (body.password or "").strip()
        if not password:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="password must not be empty",
            )
        user.hashed_password = security.get_password_hash(password)

    if "first_name" in body.model_fields_set:
        user.first_name = body.first_name

    if "last_name" in body.model_fields_set:
        user.last_name = body.last_name

    if "is_active" in body.model_fields_set:
        if body.is_active is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="is_active must not be null",
            )
        user.is_active = body.is_active

    # role — источник правды; is_superuser поддерживается синхронно.
    # Легаси-путь: если пришёл только is_superuser (старый фронт), выводим
    # роль из него (True → admin, False → member; owner так не разжаловать —
    # защищено проверками выше).
    if "role" in body.model_fields_set:
        if body.role is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="role must not be null",
            )
        user.role = body.role
        user.is_superuser = role_implies_superuser(body.role)
    elif "is_superuser" in body.model_fields_set:
        if body.is_superuser is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="is_superuser must not be null",
            )
        user.is_superuser = body.is_superuser
        if user.role != ROLE_OWNER:
            user.role = "admin" if body.is_superuser else "member"

    if "experimental_mode" in body.model_fields_set:
        if body.experimental_mode is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="experimental_mode must not be null",
            )
        user.experimental_mode = body.experimental_mode

    await db.commit()
    await db.refresh(user)
    await UserRepository.invalidate_cache(user.id)
    return UserRepository.to_response(user)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    user_repo: Annotated[UserRepository, Depends(get_user_repository)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    require_superuser(current_user)

    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cannot delete current user",
        )

    db_user = await _get_user_model_by_id(db, user_id)
    file_refs, cleanup_batches = await _build_user_storage_cleanup_batches(db, user_id)
    await _delete_user_related_resources(
        db,
        user_id,
        file_refs=file_refs,
    )

    await user_repo.delete(db_user)
    for refs, provider_snapshot, sandbox_snapshots_by_owner in cleanup_batches:
        background_tasks.add_task(
            cleanup_storage_files_best_effort,
            refs,
            provider_snapshot=provider_snapshot,
            sandbox_snapshots_by_owner=sandbox_snapshots_by_owner,
        )
