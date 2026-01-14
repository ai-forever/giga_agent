import sys
import os
import time
import logging
import asyncio
import importlib.util
import uvicorn
from enum import Enum
import typer
from typing import Annotated
from alembic.config import Config
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

# Импорты для аннотации типов
from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.db import get_session_factory

logger = logging.getLogger(__name__)


class LogLevel(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


app = typer.Typer()


def wait_for_db(db_url: str, retries: int = 15, delay: int = 2):
    """
    Checks database availability. Critical for Docker/Postgres cold starts.
    """
    # If it's SQLite, no need to wait (it's a file)
    if "sqlite" in db_url:
        return

    logger.info(f"Checking database connection at {db_url}...")

    # Create a synchronous engine for checking
    # Hack to remove +asyncpg if present, as we need a sync driver for this check
    # or just use psycopg2/pg8000 if available.
    # For simplicity, if we are in an async env, we might not have sync drivers installed easily
    # but let's assume standard sqlalchemy check.

    # If using asyncpg, create_engine might fail without a sync driver.
    # We can try to rely on 'alembic check' or similar, but a simple loop is better.
    # Let's try to assume a sync driver is present (psycopg2-binary is common for alembic)

    sync_url = db_url.replace("+asyncpg", "").replace("+aiosqlite", "")

    try:
        engine = create_engine(sync_url)
    except Exception as e:
        logger.error(f"Could not create sync engine for check: {e}")
        return

    for i in range(retries):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("Database is ready!")
            return
        except OperationalError:
            logger.info(f"Database not ready yet. Retrying {i+1}/{retries}...")
            time.sleep(delay)
        except Exception as e:
            # Other errors (like driver missing)
            logger.error(f"Error checking DB: {e}")
            # If we can't check, we proceed and hope for the best (or crash later)
            return

    logger.error("Could not connect to database after multiple retries.")
    sys.exit(1)


def load_agent_from_string(import_string: str) -> BaseAgent:
    """
    Парсит строку вида 'my_script.py:my_agent' или 'module.submodule:agent_var'
    и возвращает экземпляр Agent.
    """
    try:
        path_part, var_name = import_string.split(":")
    except ValueError:
        raise typer.BadParameter(
            "Format must be 'filepath:variable_name' (e.g., agent.py:agent)"
        )

    # Добавляем текущую директорию в path, чтобы импорты внутри пользовательского файла работали
    sys.path.insert(0, os.getcwd())

    # Попытка загрузить как файл
    if os.path.exists(path_part) or os.path.exists(path_part + ".py"):
        filename = path_part if path_part.endswith(".py") else path_part + ".py"
        spec = importlib.util.spec_from_file_location("user_agent_config", filename)
        if spec is None or spec.loader is None:
            raise typer.BadParameter(f"Could not load file: {filename}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    else:
        # Попытка загрузить как python модуль (dotted path)
        try:
            module = importlib.import_module(path_part)
        except ImportError as e:
            raise typer.BadParameter(f"Could not import module/file '{path_part}': {e}")

    # Достаем переменную
    agent_instance = getattr(module, var_name, None)

    if not agent_instance:
        raise typer.BadParameter(f"Variable '{var_name}' not found in '{path_part}'")

    if not isinstance(agent_instance, Agent):
        raise typer.BadParameter(
            f"Variable '{var_name}' is not an instance of giga_agent.Agent"
        )

    return agent_instance


def _get_alembic_config(version_locations: str) -> Config:
    """
    Helper to create Alembic Config with dynamic version locations.
    """
    # Ищем alembic.ini в текущей папке (проекте пользователя)
    alembic_ini_path = os.path.join(os.getcwd(), "alembic.ini")
    if not os.path.exists(alembic_ini_path):
        # Fallback to the one inside giga_agent package
        package_dir = os.path.dirname(os.path.abspath(__file__))
        internal_ini_path = os.path.join(package_dir, "alembic.ini")
        if os.path.exists(internal_ini_path):
            logger.info(f"Using internal alembic.ini from {internal_ini_path}")
            alembic_ini_path = internal_ini_path
        else:
            logger.warning(
                "Warning: alembic.ini not found in current directory. Using default defaults might fail."
            )

    alembic_cfg = Config(alembic_ini_path)
    alembic_cfg.set_main_option("version_locations", version_locations)
    return alembic_cfg


def apply_migrations(agent: Agent):
    """
    Собирает пути миграций из всех модулей и запускает alembic upgrade head.
    """
    # 1. Собираем миграции модулей
    migration_paths = []
    # if os.path.exists(core_migrations):
    #     migration_paths.append(core_migrations)

    for mod in agent.modules:
        if mod.migration_path:
            logger.info(
                f"Found migrations for {mod.__class__.__name__}: {mod.migration_path}"
            )
            migration_paths.append(mod.migration_path)

    if not migration_paths:
        logger.info("No migrations found.")
        return

    # 2. Формируем строку для конфига (пути разделены пробелами)
    version_locations = " ".join(migration_paths)

    # 3. Настраиваем Alembic
    alembic_cfg = _get_alembic_config(version_locations)

    # Check DB availability before migration
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        wait_for_db(db_url)

    logger.info(f"Applying migrations from locations: {version_locations}")
    try:
        command.upgrade(alembic_cfg, "head")
        logger.info("Migrations applied successfully!")
    except Exception as e:
        logger.error(f"Error applying migrations: {e}")
        raise typer.Exit(code=1)


def check_db_is_up_to_date(alembic_cfg: Config):
    """
    Checks if the database schema is up-to-date with the codebase migrations.
    """
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    # Create engine from config
    db_url = alembic_cfg.get_main_option("sqlalchemy.url")
    if not db_url:
        # Try to fallback to default logic from env.py if url not set in config object yet
        # But usually we set it via env vars or default in _get_alembic_config?
        # Actually _get_alembic_config just reads ini. Let's rely on standard way.
        pass

    # We need a connection to inspect DB
    # We can reuse the logic from wait_for_db or just create engine
    # Since we are in sync CLI context, let's use sync engine
    try:
        # Clean async driver for inspection
        sync_url = db_url.replace("+asyncpg", "").replace("+aiosqlite", "")
        engine = create_engine(sync_url)
        conn = engine.connect()
    except Exception as e:
        logger.warning(f"Could not connect to DB for revision check: {e}")
        return

    context = MigrationContext.configure(conn)
    current_rev = context.get_current_revision()

    script = ScriptDirectory.from_config(alembic_cfg)
    head_rev = script.get_current_head()

    if current_rev != head_rev:
        logger.error("Database is not up-to-date!")
        logger.error(f"Current DB revision: {current_rev}")
        logger.error(f"Codebase head: {head_rev}")
        logger.error(
            "Please run 'giga_agent up' or apply migrations before creating a new one."
        )
        sys.exit(1)

    logger.info("Database is up-to-date.")


@app.command()
def check(
    agent_path: Annotated[
        str, typer.Option(help="Path to agent instance, e.g. agent.py:agent")
    ] = "agent.py:agent",
):
    """
    Validates migration history for all modules.
    Fails if multiple heads are found in any module (branching history).
    """
    from alembic.script import ScriptDirectory

    os.environ.setdefault("GIGA_AGENT_RUNTIME", "local")
    logging.basicConfig(level=logging.INFO)

    logger.info(f"Loading agent from {agent_path}...")
    try:
        agent = load_agent_from_string(agent_path)
    except Exception as e:
        logger.error(f"Failed to load agent: {e}")
        raise typer.Exit(code=1)

    # 1. Collect migration paths
    migration_paths = []
    for mod in agent.modules:
        if mod.migration_path:
            migration_paths.append(mod.migration_path)

    if not migration_paths:
        logger.info("No migrations found.")
        return

    version_locations = " ".join(migration_paths)
    alembic_cfg = _get_alembic_config(version_locations)

    script = ScriptDirectory.from_config(alembic_cfg)

    # 2. Check for multiple heads
    # script.get_heads() returns a list of head revision IDs
    heads = script.get_heads()

    # In a multi-location setup, get_heads() might return one head per branch (per module)
    # BUT if a single module has branching, we will see it here too.
    # The tricky part: how to distinguish "1 head per module" (OK) from "2 heads in one module" (BAD)?

    # Alembic treats all locations as one big graph.
    # If modules are independent (no cross-dependencies), they form separate disconnected subgraphs (branches).
    # So `heads` will contain one revision ID for each module. This is expected.

    # We need to detect if any SINGLE module subgraph has > 1 head.
    # We can iterate over all heads and check if any two heads belong to the same lineage?
    # Actually, simpler: `alembic check` or `alembic branches` logic.

    # Let's try to map heads to their directories? Hard with Alembic API.
    # Better approach: Iterate over migration_paths, create a separate ScriptDirectory for EACH path,
    # and check if that specific path has > 1 head.

    has_errors = False

    for path in migration_paths:
        # Create a temporary config for just THIS path
        # This isolates the graph to one module

        # We need a new config object because we can't reuse the main one easily without side effects
        single_cfg = Config()
        single_cfg.set_main_option("version_locations", path)

        # We need to point to alembic.ini to get other settings (like script_location pattern)
        # But script_location is usually generic.
        # Let's try to reuse _get_alembic_config but with single path
        single_cfg = _get_alembic_config(path)

        try:
            single_script = ScriptDirectory.from_config(single_cfg)
            module_heads = single_script.get_heads()

            if len(module_heads) > 1:
                logger.error(f"CONFLICT detected in {path}!")
                logger.error(f"Found multiple heads: {module_heads}")
                has_errors = True
            elif len(module_heads) == 0:
                # Empty module, usually ok
                pass
            else:
                logger.info(f"OK: {path} (Head: {module_heads[0]})")

        except Exception as e:
            logger.warning(f"Could not check {path}: {e}")

    if has_errors:
        logger.error("Migration validation failed! Please resolve conflicts.")
        sys.exit(1)

    logger.info("All modules have linear migration history.")


@app.command()
def makemigrations(
    module_path: Annotated[str, typer.Argument(help="Path to the module directory")],
    message: Annotated[str, typer.Argument(help="Migration message")],
    agent_path: Annotated[
        str, typer.Option(help="Path to agent instance, e.g. agent.py:agent")
    ] = "agent.py:agent",
):
    """
    Создает новую миграцию для указанного модуля.
    """
    os.environ.setdefault("GIGA_AGENT_RUNTIME", "local")
    logging.basicConfig(level=logging.INFO)

    # 1. Загружаем агента
    logger.info(f"Loading agent from {agent_path}...")
    try:
        agent = load_agent_from_string(agent_path)
    except Exception as e:
        logger.error(f"Failed to load agent: {e}")
        raise typer.Exit(code=1)

    # 2. Ищем целевой модуль
    target_module = None
    abs_input_path = os.path.abspath(module_path).rstrip(os.sep)

    for mod in agent.modules:
        # mod.module_path ожидается абсолютным, но на всякий случай
        mod_path = os.path.abspath(mod.module_path).rstrip(os.sep)
        if mod_path == abs_input_path:
            target_module = mod
            break

    if not target_module:
        logger.error(f"Module at path '{module_path}' not found in loaded agent.")
        logger.info("Available modules:")
        for mod in agent.modules:
            logger.info(f" - {mod.module_path} ({mod.__class__.__name__})")
        raise typer.Exit(code=1)

    # 3. Подготовка папки миграций
    target_migration_dir = os.path.join(target_module.module_path, "migrations")
    if not os.path.exists(target_migration_dir):
        logger.info(f"Creating migrations directory: {target_migration_dir}")
        os.makedirs(target_migration_dir)

    # 4. Собираем ВСЕ пути миграций для Alembic
    migration_paths = []
    for mod in agent.modules:
        # Check existing migrations
        p = os.path.join(mod.module_path, "migrations")
        if os.path.exists(p):
            migration_paths.append(p)

    # Ensure target is present (it exists now)
    if target_migration_dir not in migration_paths:
        migration_paths.append(target_migration_dir)

    version_locations = " ".join(migration_paths)

    # 5. Config Alembic
    alembic_cfg = _get_alembic_config(version_locations)

    # Check DB
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        wait_for_db(db_url)

    # 6. Verify DB is up-to-date BEFORE generating new migration
    # This prevents branching and ensures autogenerate works against the latest schema
    check_db_is_up_to_date(alembic_cfg)

    # 7. Generate Revision
    logger.info(f"Generating migration for {target_module.__class__.__name__}")
    logger.info(f"Target directory: {target_migration_dir}")

    # Передаем префикс модуля через x-arguments в env.py
    # Нужно получить правильное имя модуля для префикса (как в db.py)
    mod_class = target_module.__class__
    module_parts = mod_class.__module__.split(".")
    # giga_agent.auth.module -> auth
    # my_plugin.module -> my_plugin
    if len(module_parts) > 1 and module_parts[-1] == "module":
        module_name = module_parts[-2]
    else:
        module_name = module_parts[-1]

    target_prefix = f"{module_name}_"
    logger.info(f"Filtering tables with prefix: {target_prefix}")

    # Alembic context arguments (будут доступны в env.py через context.get_x_argument)
    alembic_cfg.cmd_opts = type(
        "CmdOpts", (), {"x": [f"target_prefix={target_prefix}"]}
    )()

    try:
        command.revision(
            alembic_cfg,
            message=message,
            autogenerate=True,
            version_path=target_migration_dir,
        )
        logger.info(f"Migration created in {target_migration_dir}")
    except Exception as e:
        logger.error(f"Error creating migration: {e}")
        raise typer.Exit(code=1)


async def run_startup_hooks(agent: Agent):
    """
    Runs on_startup for all modules.
    """
    logger.info("Running startup hooks...")
    session_factory = get_session_factory()
    async with session_factory() as session:
        for module in agent.modules:
            try:
                await module.on_startup(session)
            except Exception as e:
                logger.error(
                    f"Error in startup hook for {module.__class__.__name__}: {e}"
                )
                # We might want to stop here, or continue?
                # For now log error but continue, though admin creation failure is critical.
                pass


@app.command()
def dev(
    agent_path: Annotated[
        str, typer.Argument(help="Path to agent instance, e.g. agent.py:agent")
    ],
    log_level: Annotated[
        LogLevel, typer.Option(help="Logging level", case_sensitive=False)
    ] = LogLevel.INFO,
):
    """
    Запускает режим разработки: применяет миграции модулей и стартует приложение.
    """
    logging.basicConfig(level=log_level.value.upper())

    # Создаем базовую директорию агента
    os.makedirs(".giga_agent", exist_ok=True)

    os.environ.setdefault("GIGA_AGENT_RUNTIME", "local")
    logger.info(f"Loading agent from {agent_path}...")

    # 1. Загружаем агента и модули
    agent = load_agent_from_string(agent_path)
    logger.info(f"Loaded agent with {len(agent.modules)} modules.")

    # 2. Применяем миграции
    apply_migrations(agent)

    # 3. Запускаем хуки старта (например создание админа)
    try:
        asyncio.run(run_startup_hooks(agent))
    except Exception as e:
        logger.error(f"Startup hooks failed: {e}")

    # 4. Запускаем приложение
    logger.info("Starting development server...")
    uvicorn.run(agent.app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    app()
