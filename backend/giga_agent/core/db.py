import asyncio
from typing import Any, AsyncGenerator, Optional
from sqlalchemy import JSON, event
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
    AsyncEngine,
)
from giga_agent.conf import get_settings


class Base(DeclarativeBase):
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        # Пропускаем сам Base и абстрактные классы
        if cls.__name__ == "Base" or cls.__dict__.get("__abstract__", False):
            return

        # Логика автоматического префикса
        # Цель: добавить имя модуля к названию таблицы (auth_users, billing_orders)

        # 1. Определяем имя модуля
        module_parts = cls.__module__.split(".")

        # Специальная обработка для core моделей (giga_agent.models.*)
        # Они используют префикс core_ явно в __tablename__ и не требуют автопрефикса
        if (
            len(module_parts) >= 2
            and module_parts[0] == "giga_agent"
            and module_parts[1] == "models"
        ):
            # Core модели - не добавляем автоматический префикс
            return

        # giga_agent.modules.auth.models -> auth
        # my_plugin.models -> my_plugin
        if len(module_parts) > 1 and module_parts[-1] == "models":
            module_name = module_parts[-2]
        else:
            module_name = module_parts[-1]

        prefix = f"{module_name}_"

        # 2. Получаем текущее имя таблицы
        # В DeclarativeBase имя таблицы уже доступно через __tablename__ или __table__.name
        current_name = getattr(cls, "__tablename__", None)

        # Если имя не задано, можно сгенерировать его (как declared_attr)
        if not current_name:
            current_name = cls.__name__.lower()
            cls.__tablename__ = current_name

        # 3. Добавляем префикс, если его нет
        if current_name and not current_name.startswith(prefix):
            new_name = prefix + current_name

            # Обновляем атрибут класса
            cls.__tablename__ = new_name

            # Если таблица (Table object) уже создана (метакласс отработал), обновляем её
            if hasattr(cls, "__table__"):
                table = cls.__table__
                if table.name != new_name:
                    # Хак для переименования таблицы в метаданных SQLAlchemy
                    # Удаляем старую запись
                    cls.metadata.remove(table)

                    # Меняем имя объекта таблицы
                    table.name = new_name

                    # Регистрируем под новым именем
                    cls.metadata._add_table(new_name, table.schema, table)


def JSON_VARIANT():
    """
    Returns JSONB for PostgreSQL and JSON (Text) for others (SQLite).
    Use this for all JSON columns.
    """
    return JSON().with_variant(JSONB, "postgresql")


def _set_sqlite_foreign_keys(
    dbapi_connection: Any,
    connection_record: Any,
) -> None:
    del connection_record
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def configure_sqlite_foreign_keys(engine: AsyncEngine, url: str) -> None:
    if "sqlite" not in url:
        return
    event.listen(engine.sync_engine, "connect", _set_sqlite_foreign_keys)


def get_db_url() -> str:
    """
    Determines database URL based on environment.
    """
    settings = get_settings()
    runtime = settings.giga_agent_runtime

    if runtime in ("local", "cli"):
        explicit = (settings.giga_agent_database_url or "").strip()
        if explicit:
            return explicit

        from giga_agent.core.paths import ensure_giga_agent_dir

        db_path = ensure_giga_agent_dir() / "db" / "local.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite+aiosqlite:///{db_path}"

    # For docker/production, expect DB URL in settings/env.
    return (
        settings.giga_agent_database_url
        or "postgresql+asyncpg://user:pass@localhost/dbname"
    )


_engine: Optional[AsyncEngine] = None
_session_factory = None


async def get_engine():
    global _engine
    if _engine is None:
        url = await asyncio.to_thread(get_db_url)
        _engine = await asyncio.to_thread(create_async_engine, url, echo=False)
        configure_sqlite_foreign_keys(_engine, url)
    return _engine


async def get_session_factory():
    global _session_factory
    if _session_factory is None:
        engine = await get_engine()
        _session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return _session_factory


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency for FastAPI.
    """
    factory = await get_session_factory()
    async with factory() as session:
        yield session


async def dispose_engine() -> None:
    """
    Dispose the global AsyncEngine (and reset session factory).

    Needed for clean CLI shutdown on SQLite/aiosqlite where a connection worker
    thread can keep the Python process alive.
    """
    global _engine, _session_factory
    engine = _engine
    _engine = None
    _session_factory = None
    if engine is None:
        return
    try:
        await engine.dispose()
    except Exception:
        # Best-effort cleanup; callers decide whether to surface failures.
        return
