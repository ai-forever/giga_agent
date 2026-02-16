from datetime import timedelta
from typing import Annotated

from jwt.exceptions import ExpiredSignatureError, PyJWTError
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.core.db import get_session
from giga_agent.modules.auth import security
from giga_agent.modules.auth.security import ACCESS_TOKEN_EXPIRE_MINUTES
from giga_agent.core.events import event_bus
from giga_agent.modules.auth.events import UserCreatedEvent
from giga_agent.models.users import (
    UserShort,
    UserRepository,
    UserResponse,
    UserCreate,
    UserSettingsUpdate,
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
    return current_user


@router.patch("/users/me/settings", response_model=UserShort)
async def update_user_settings(
    body: UserSettingsUpdate,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    user_repo: Annotated[UserRepository, Depends(get_user_repository)],
):
    """Обновить настройки текущего пользователя (merge с существующими)"""
    return await user_repo.update_settings(
        current_user.id,
        body.settings,
    )


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
