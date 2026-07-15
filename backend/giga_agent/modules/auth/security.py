import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from giga_agent.conf import get_settings

ACCESS_TOKEN_EXPIRE_MINUTES = None  # None = tokens never expire


def verify_password(plain_password: str, hashed_password: str) -> bool:
    # bcrypt.checkpw requires bytes
    password_bytes = plain_password.encode("utf-8")
    hash_bytes = hashed_password.encode("utf-8")
    return bcrypt.checkpw(password_bytes, hash_bytes)


def get_password_hash(password: str) -> str:
    # bcrypt.hashpw requires bytes and returns bytes
    pwd_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt()
    hashed_bytes = bcrypt.hashpw(pwd_bytes, salt)
    return hashed_bytes.decode("utf-8")


# Фиктивный хэш для выравнивания тайминга логина: когда аккаунт не найден, всё равно
# прогоняем verify_password против него, чтобы время ответа не выдавало, существует ли
# email (тайминг-enumeration). Считается один раз при импорте.
_DUMMY_PASSWORD_HASH = get_password_hash("giga-agent-dummy-password")


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    settings = get_settings()
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
        to_encode.update({"exp": expire})

    # Add JTI if not present
    if "jti" not in to_encode:
        to_encode["jti"] = str(uuid.uuid4())

    encoded_jwt = jwt.encode(
        to_encode,
        settings.giga_agent_secret_key,
        algorithm=settings.giga_agent_auth_algorithm,
    )
    return encoded_jwt


def get_user_id_from_token(token: str) -> uuid.UUID:
    settings = get_settings()
    payload = jwt.decode(
        token,
        settings.giga_agent_secret_key,
        algorithms=[settings.giga_agent_auth_algorithm],
    )
    user_id_str: str | None = payload.get("user_id")
    if user_id_str is None:
        raise ValueError("user_id is missing from token")
    return uuid.UUID(user_id_str)
