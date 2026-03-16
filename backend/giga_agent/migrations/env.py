import asyncio
import os
import logging
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from giga_agent.conf import get_settings
from giga_agent.core.db import configure_sqlite_foreign_keys

# config - это объект конфигурации Alembic
config = context.config

# Интерпретация настроек логгирования
if config.config_file_name is not None:
    # If the application/CLI already configured logging (e.g. structlog + Rich),
    # don't let Alembic override handlers/formatters via fileConfig().
    root = logging.getLogger()
    already_configured = any(
        getattr(h, "_giga_agent_cli_handler", False) for h in root.handlers
    )
    force_file_config = get_settings().giga_agent_alembic_fileconfig
    if force_file_config or not already_configured:
        # IMPORTANT: keep app loggers alive; Alembic's default disables them.
        fileConfig(config.config_file_name, disable_existing_loggers=False)

# ----------------------------------------------------------------------
# ДИНАМИЧЕСКИЙ URL БД
# ----------------------------------------------------------------------
# Приоритет:
# 1. Переменная окружения GIGA_AGENT_DATABASE_URL
# 2. Значение из alembic.ini
section = config.get_section(config.config_ini_section)
db_url = get_settings().giga_agent_database_url or section.get("sqlalchemy.url")

# Фоллбек для локальной разработки
if not db_url:
    from giga_agent.core.paths import ensure_giga_agent_dir

    db_path = ensure_giga_agent_dir() / "db" / "local.db"
    db_url = f"sqlite+aiosqlite:///{db_path}"

# Создаем папку для БД, если это SQLite
if "sqlite" in db_url:
    # sqlite+aiosqlite:///path/to/file
    # Убираем протокол
    path = db_url.split(":///")[-1] 
    # Если путь абсолютный (////), split вернет /path/to/file, что верно для unix
    
    directory = os.path.dirname(path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)

section["sqlalchemy.url"] = db_url
config.set_section_option(config.config_ini_section, "sqlalchemy.url", db_url)

# ----------------------------------------------------------------------
# METADATA И МОДЕЛИ
# ----------------------------------------------------------------------
# Alembic должен видеть модели для autogenerate.
# В нашем случае мы полагаемся на то, что `giga_agent dev` уже загрузил
# агент и его модули, поэтому модели уже импортированы в память.
# Нам нужно найти Base, в котором они зарегистрированы.

target_metadata = None

# Попытка найти Base в giga_agent.core.db
try:
    from giga_agent.core.db import Base
    
    # Импортируем core модели, чтобы они зарегистрировались в Base.metadata
    # Это необходимо для autogenerate
    try:
        import giga_agent.models  # noqa: F401
    except ImportError:
        pass
    
    target_metadata = Base.metadata
except ImportError:
    # Если Base не найден, autogenerate не будет работать для новых моделей,
    # но существующие миграции применятся.
    pass

def include_object(object, name, type_, reflected, compare_to):
    """
    Hook to filter objects during autogeneration.
    Used to implement modular migrations by filtering tables by prefix.
    """
    # Получаем аргументы, переданные через командную строку (-x target_prefix=...)
    # В CLI мы передаем их через alembic_cfg.cmd_opts.x
    x_args = context.get_x_argument(as_dictionary=True)
    target_prefix = x_args.get("target_prefix")

    if type_ == "table":
        # 1. Режим генерации миграции для конкретного модуля (есть target_prefix)
        if target_prefix:
            # Если таблица не начинается с префикса модуля, игнорируем её полностью
            # Это предотвращает генерацию DROP TABLE для чужих модулей
            if not name.startswith(target_prefix):
                return False
            return True

        # 2. Обычный режим (up/dev) или если префикс не задан
        # Защита от удаления таблиц отключенных модулей:
        # Если таблица есть в БД (reflected=True), но её нет в метаданных (мы её не загрузили)
        if reflected and target_metadata and name not in target_metadata.tables:
            # Игнорируем её (не удаляем)
            return False

    return True

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    version_table = config.get_main_option("version_table") or "alembic_version"
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # Включаем batch mode для SQLite
        render_as_batch=url.startswith("sqlite"),
        version_table=version_table,
        # Module scopes use dedicated version tables and may need multiple rows if a table
        # is bootstrapped without a PK constraint from a previous setup.
        version_table_pk=False,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations in 'online' mode."""
    # Определяем, используем ли мы SQLite
    is_sqlite = connection.dialect.name == "sqlite"
    version_table = config.get_main_option("version_table") or "alembic_version"

    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # КРИТИЧНО ДЛЯ SQLITE: Включаем render_as_batch
        render_as_batch=is_sqlite,
        version_table=version_table,
        # Keep version table creation compatible with existing installs and module scopes.
        version_table_pk=False,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """In this scenario we need to create an Engine and associate a connection with the context."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    configure_sqlite_foreign_keys(
        connectable,
        config.get_main_option("sqlalchemy.url"),
    )

    try:
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
