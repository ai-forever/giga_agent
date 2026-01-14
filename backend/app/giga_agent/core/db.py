import os
from typing import Any, AsyncGenerator
from sqlalchemy import JSON
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession


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
        # giga_agent.auth.models -> auth
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


def get_db_url() -> str:
    """
    Determines database URL based on environment.
    """
    runtime = os.getenv("GIGA_AGENT_RUNTIME", "local")
    
    if runtime == "local":
        return "sqlite+aiosqlite:///.giga_agent/db/local.db"
    
    # For docker/production, expect DATABASE_URL
    return os.getenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/dbname")


_engine = None
_session_factory = None

def get_engine():
    global _engine
    if _engine is None:
        url = get_db_url()
        _engine = create_async_engine(url, echo=False)
    return _engine

def get_session_factory():
    global _session_factory
    if _session_factory is None:
        engine = get_engine()
        _session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return _session_factory

async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency for FastAPI.
    """
    factory = get_session_factory()
    async with factory() as session:
        yield session
