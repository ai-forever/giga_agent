import time
import uuid
from datetime import timedelta
from typing import Annotated

from jwt.exceptions import ExpiredSignatureError, PyJWTError
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.core.db import get_session
from giga_agent.core.module import collect_module_secrets
from giga_agent.models.embedding import EmbeddingRepository
from giga_agent.models.image_generator import ImageGeneratorRepository
from giga_agent.models.llm import LLMRepository
from giga_agent.models.search_engine import SearchEngineRepository
from giga_agent.modules.auth import security
from giga_agent.modules.auth.security import ACCESS_TOKEN_EXPIRE_MINUTES
from giga_agent.core.events import event_bus
from giga_agent.modules.auth.events import UserCreatedEvent
from giga_agent.models.users import (
    User,
    UserShort,
    UserRepository,
    UserResponse,
    UserCreate,
    UserUpdate,
)

router = APIRouter(tags=["auth"])

AUTH_COOKIE_NAME = "access_token"
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)


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

from pydantic import BaseModel


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
        detail=f"Invalid value for {field_name}: record must exist, belong to user, and be active",
    )


async def _validate_llm_id(
    db: AsyncSession,
    owner_id: uuid.UUID,
    llm_id: uuid.UUID,
) -> None:
    llm = await LLMRepository.get_cached_or_db(
        llm_id,
        session=db,
    )
    if llm is None or llm.owner_id != owner_id or not llm.is_active:
        raise _invalid_reference_error("llm_id")


async def _validate_fast_llm_id(
    db: AsyncSession,
    owner_id: uuid.UUID,
    fast_llm_id: uuid.UUID,
) -> None:
    llm = await LLMRepository.get_cached_or_db(
        fast_llm_id,
        session=db,
    )
    if llm is None or llm.owner_id != owner_id or not llm.is_active:
        raise _invalid_reference_error("fast_llm_id")


async def _validate_embedding_id(
    db: AsyncSession,
    owner_id: uuid.UUID,
    embedding_id: uuid.UUID,
) -> None:
    embedding = await EmbeddingRepository.get_cached_or_db(
        embedding_id,
        session=db,
    )
    if embedding is None or embedding.owner_id != owner_id or not embedding.is_active:
        raise _invalid_reference_error("embedding_id")


async def _validate_image_generator_id(
    db: AsyncSession,
    owner_id: uuid.UUID,
    image_generator_id: uuid.UUID,
) -> None:
    generator = await ImageGeneratorRepository.get_cached_or_db(
        image_generator_id,
        session=db,
    )
    if generator is None or generator.owner_id != owner_id or not generator.is_active:
        raise _invalid_reference_error("image_generator_id")


async def _validate_search_engine_id(
    db: AsyncSession,
    owner_id: uuid.UUID,
    search_engine_id: uuid.UUID,
) -> None:
    engine = await SearchEngineRepository.get_cached_or_db(
        search_engine_id,
        session=db,
    )
    if engine is None or engine.owner_id != owner_id or not engine.is_active:
        raise _invalid_reference_error("search_engine_id")


async def _validate_llm_secret_references(
    *,
    request: Request,
    db: AsyncSession,
    owner_id: uuid.UUID,
    merged_secrets: dict,
) -> None:
    agent = getattr(request.app.state, "agent", None)
    if agent is None:
        return

    for secret_meta in collect_module_secrets(agent.modules):
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

        try:
            await _validate_llm_id(db, owner_id, llm_id)
        except HTTPException as exc:
            if exc.status_code != status.HTTP_422_UNPROCESSABLE_ENTITY:
                raise
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Invalid value for secrets.{secret_name}: record must exist, "
                    "belong to user, and be active"
                ),
            )


# ============ Endpoints ============


@router.post("/token", response_model=Token)
async def login_for_access_token(
    request: Request,
    response: Response,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    user_repo: Annotated[UserRepository, Depends(get_user_repository)],
):
    user = await user_repo.get_by_email(form_data.username)
    if not user or not security.verify_password(
        form_data.password, user.hashed_password
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
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
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=access_token,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
    )
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response):
    response.delete_cookie(key=AUTH_COOKIE_NAME, path="/")


@router.get("/users/me", response_model=UserShort)
async def read_users_me(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
):
    time.sleep(1)
    return current_user


@router.patch("/users/me", response_model=UserShort)
async def update_user(
    body: UserUpdate,
    request: Request,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """Частично обновить профиль текущего пользователя."""
    if not body.model_fields_set:
        return current_user

    user = await _get_user_model_by_id(db, current_user.id)

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
            owner_id=current_user.id,
            merged_secrets=merged_secrets,
        )
        user.secrets = merged_secrets

    if "llm_id" in body.model_fields_set:
        if body.llm_id is not None:
            await _validate_llm_id(db, current_user.id, body.llm_id)
        user.llm_id = body.llm_id

    if "fast_llm_id" in body.model_fields_set:
        if body.fast_llm_id is not None:
            await _validate_fast_llm_id(db, current_user.id, body.fast_llm_id)
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

    await db.commit()
    await db.refresh(user)
    await UserRepository.invalidate_cache(user.id)
    return UserRepository.to_short(user)


@router.post("/users", response_model=UserResponse)
async def create_user(
    user: UserCreate,
    user_repo: Annotated[UserRepository, Depends(get_user_repository)],
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
):
    if await user_repo.exists_by_email(user.email):
        raise HTTPException(status_code=400, detail="Email already registered")

    hashed_password = security.get_password_hash(user.password)

    db_user = await user_repo.create(
        email=user.email,
        hashed_password=hashed_password,
        first_name=user.first_name,
        last_name=user.last_name,
        is_active=user.is_active,
        is_superuser=user.is_superuser,
    )

    await event_bus.publish(UserCreatedEvent(user_id=db_user.id, email=db_user.email))

    return db_user
