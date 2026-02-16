import sys
import os
import time
import logging
import asyncio
import traceback
import importlib
import importlib.util
import uvicorn
from enum import Enum
import typer
from typing import Annotated, Tuple
from types import ModuleType
from fastapi import FastAPI
from langgraph.graph.state import CompiledStateGraph
from alembic.config import Config
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

# Импорты для аннотации типов
from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.agent.types import AgentState, Context
from giga_agent.core.db import get_session_factory, get_db_url

logger = logging.getLogger(__name__)


def _get_core_models_migration_path() -> str:
    """
    Returns the absolute path to core models migrations directory.
    Core models are located in giga_agent/models/.
    """
    package_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(package_dir, "models", "migrations")


class LogLevel(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class CLIException(Exception):
    pass


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


def _parse_import_string(
    import_string: str, expected_parts: int, format_hint: str
) -> tuple[str, ...]:
    parts = import_string.split(":")
    if len(parts) != expected_parts:
        raise typer.BadParameter(f"Format must be {format_hint}")
    return tuple(parts)


def _ensure_cwd_in_sys_path() -> None:
    # Добавляем текущую директорию в path, чтобы импорты внутри пользовательского файла работали
    cwd = os.getcwd()
    if cwd not in sys.path:
        sys.path.insert(0, cwd)


def _load_module_from_path(path_part: str, module_alias: str) -> ModuleType:
    _ensure_cwd_in_sys_path()

    if os.path.exists(path_part) or os.path.exists(path_part + ".py"):
        filename = path_part if path_part.endswith(".py") else path_part + ".py"
        spec = importlib.util.spec_from_file_location(module_alias, filename)
        if spec is None or spec.loader is None:
            raise typer.BadParameter(f"Could not load file: {filename}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    try:
        return importlib.import_module(path_part)
    except ImportError as e:
        raise typer.BadParameter(f"Could not import module/file '{path_part}': {e}")


def _get_module_attr(module: ModuleType, attr_name: str, path_part: str):
    value = getattr(module, attr_name, None)
    if value is None:
        raise typer.BadParameter(f"Variable '{attr_name}' not found in '{path_part}'")
    return value


def load_agent_from_string(import_string: str) -> BaseAgent:
    """
    Парсит строку вида 'my_script.py:my_agent' или 'module.submodule:agent_var'
    и возвращает экземпляр Agent.
    """
    path_part, var_name = _parse_import_string(
        import_string,
        expected_parts=2,
        format_hint="'filepath:variable_name' (e.g., agent.py:agent)",
    )

    module = _load_module_from_path(path_part, "user_agent_config")
    agent_instance = _get_module_attr(module, var_name, path_part)

    if not isinstance(agent_instance, BaseAgent):
        raise typer.BadParameter(
            f"Variable '{var_name}' is not an instance of giga_agent.Agent"
        )

    return agent_instance


def load_graph_and_app_from_string(
    import_string: str,
) -> Tuple[CompiledStateGraph[AgentState, Context], FastAPI]:
    """
    Парсит строку вида 'my_script.py:graph:app' или 'module.submodule:graph:app'
    и возвращает экземпляр объект графа и объект FastAPI.
    """
    path_part, graph_var, app_var = _parse_import_string(
        import_string,
        expected_parts=3,
        format_hint="'filepath:graph_var:app_var' (e.g., agent.py:graph:app)",
    )

    module = _load_module_from_path(path_part, "user_graph_config")
    graph_instance = _get_module_attr(module, graph_var, path_part)
    app_instance = _get_module_attr(module, app_var, path_part)

    if not isinstance(graph_instance, CompiledStateGraph):
        raise typer.BadParameter(
            f"Variable '{graph_var}' is not a CompiledStateGraph instance"
        )

    if not isinstance(app_instance, FastAPI):
        raise typer.BadParameter(f"Variable '{app_var}' is not a FastAPI instance")

    return graph_instance, app_instance


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


def apply_migrations(agent: BaseAgent):
    """
    Собирает пути миграций из всех модулей и запускает alembic upgrade head.
    """
    # 1. Собираем миграции модулей
    migration_paths = []

    # 1.1. Добавляем core модели (giga_agent/models)
    core_migrations = _get_core_models_migration_path()
    if os.path.exists(core_migrations):
        logger.info(f"Found core models migrations: {core_migrations}")
        migration_paths.append(core_migrations)

    # 1.2. Добавляем миграции модулей
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

    # Check DB availability before migration
    db_url = get_db_url()

    # 3. Настраиваем Alembic
    alembic_cfg = _get_alembic_config(version_locations)
    alembic_cfg.set_section_option("alembic", "sqlalchemy.url", db_url)

    if db_url:
        wait_for_db(db_url)

    logger.info(f"Applying migrations from locations: {version_locations}")
    try:
        command.upgrade(alembic_cfg, "head")
        logger.info("Migrations applied successfully!")
    except Exception as e:
        logger.exception("Error applying migrations")
        typer.secho(f"Error applying migrations: {e}", err=True, fg=typer.colors.RED)
        traceback.print_exc()
        raise typer.Exit(code=1)


def check_db_is_up_to_date(alembic_cfg: Config):
    """
    Checks if the database schema is up-to-date with the codebase migrations.
    """
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    # Create engine from config
    db_url = get_db_url()
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

    # 1.1. Добавляем core модели
    core_migrations = _get_core_models_migration_path()
    if os.path.exists(core_migrations):
        migration_paths.append(core_migrations)

    # 1.2. Добавляем миграции модулей
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
    agent_path: Annotated[
        str, typer.Option(help="Path to agent instance, e.g. agent.py:agent")
    ] = "agent.py:agent",
    message: Annotated[str, typer.Option(help="Migration message")] = "",
):
    """
    Создает новую миграцию для указанного модуля.

    Примеры:
        giga_agent makemigrations giga_agent/auth --agent-path agent.py:agent -m "add auth"
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

    target_migration_dir = os.path.join(target_module.module_path, "migrations")
    target_name = target_module.__class__.__name__

    # Получаем префикс модуля
    mod_class = target_module.__class__
    module_parts = mod_class.__module__.split(".")
    # giga_agent.modules.auth.module -> auth
    # my_plugin.module -> my_plugin
    if len(module_parts) > 1 and module_parts[-1] == "module":
        module_name = module_parts[-2]
    else:
        module_name = module_parts[-1]
    target_prefix = f"{module_name}_"

    # 3. Подготовка папки миграций
    if not os.path.exists(target_migration_dir):
        logger.info(f"Creating migrations directory: {target_migration_dir}")
        os.makedirs(target_migration_dir)

    # 4. Собираем ВСЕ пути миграций для Alembic
    migration_paths = []

    # 4.1. Core models migrations
    core_migrations = _get_core_models_migration_path()
    if os.path.exists(core_migrations):
        migration_paths.append(core_migrations)

    # 4.2. Module migrations
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
    db_url = get_db_url()
    if db_url:
        wait_for_db(db_url)

    # 6. Verify DB is up-to-date BEFORE generating new migration
    # This prevents branching and ensures autogenerate works against the latest schema
    check_db_is_up_to_date(alembic_cfg)

    # 7. Generate Revision
    logger.info(f"Generating migration for {target_name}")
    logger.info(f"Target directory: {target_migration_dir}")
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


async def run_startup_hooks(agent: BaseAgent):
    """
    Runs on_startup for all modules.
    """
    logger.info("Running startup hooks...")
    session_factory = await get_session_factory()
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
    graph_and_app_path: Annotated[
        str, typer.Argument(help="Path to agent instance, e.g. agent.py:agent")
    ],
    log_level: Annotated[
        LogLevel, typer.Option(help="Logging level", case_sensitive=False)
    ] = LogLevel.INFO,
    host: Annotated[str, typer.Option(help="Host to bind to")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port to bind to")] = 9090,
    no_reload: Annotated[bool, typer.Option(help="Disable auto-reload")] = False,
):
    """
    Запускает режим разработки: применяет миграции модулей и стартует приложение.
    """
    try:
        from langgraph_api.cli import run_server  # type: ignore
    except ImportError:
        py_version_msg = ""
        if sys.version_info < (3, 11):
            py_version_msg = (
                "\n\nNote: The in-mem server requires Python 3.11 or higher to be installed."
                f" You are currently using Python {sys.version_info.major}.{sys.version_info.minor}."
                ' Please upgrade your Python version before installing "langgraph-cli[inmem]".'
            )
        try:
            from importlib import util

            if not util.find_spec("langgraph_api"):
                raise CLIException(
                    "Required package 'langgraph-api' is not installed.\n"
                    "Please install it with:\n\n"
                    '    pip install -U "langgraph-cli[inmem]"'
                    f"{py_version_msg}"
                ) from None
        except ImportError:
            raise CLIException(
                "Could not verify package installation. Please ensure Python is up to date and\n"
                "langgraph-cli is installed with the 'inmem' extra: pip install -U \"langgraph-cli[inmem]\""
                f"{py_version_msg}"
            ) from None
        raise CLIException(
            "Could not import run_server. This likely means your installation is incomplete.\n"
            "Please ensure langgraph-cli is installed with the 'inmem' extra: pip install -U \"langgraph-cli[inmem]\""
            f"{py_version_msg}"
        ) from None
    logging.basicConfig(level=log_level.value.upper())

    # Создаем базовую директорию агента
    os.makedirs(".giga_agent", exist_ok=True)

    os.environ.setdefault("GIGA_AGENT_RUNTIME", "local")
    # Cache backend (mem:// for local, redis:// for production)
    from giga_agent.core.cache import setup_cache

    setup_cache()
    logger.info(f"Loading agent from {graph_and_app_path}...")

    # 1. Загружаем агента и модули
    graph, fast_api_app = load_graph_and_app_from_string(graph_and_app_path)
    agent = graph.giga_agent
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

    path_part, graph_var, app_var = _parse_import_string(
        graph_and_app_path,
        expected_parts=3,
        format_hint="'filepath:graph_var:app_var' (e.g., agent.py:graph:app)",
    )

    # Suppress all external logs, keep only giga_agent logs at the desired level.
    # Two mechanisms needed:
    # 1) Patch dictConfig — uvicorn.Config.__init__ calls it in the parent process,
    #    which resets root logger level back to INFO.
    # 2) Patch uvicorn.run — inject root level into log_config so that the reload
    #    subprocess (fresh Python process) also gets root=WARNING via dictConfig.
    _desired_level = log_level.value.upper()
    logging.root.setLevel(logging.WARNING)
    logging.getLogger("giga_agent").setLevel(_desired_level)

    # Patch 2: uvicorn.run — inject root level into log_config for child process
    _orig_uvicorn_run = uvicorn.run

    def _uvicorn_run_with_suppression(*args, **kwargs):
        log_config = kwargs.get("log_config")
        if isinstance(log_config, dict):
            if "root" in log_config:
                log_config["root"]["level"] = "WARNING"
            if "loggers" not in log_config:
                log_config["loggers"] = {}
            log_config["loggers"]["giga_agent"] = {"level": _desired_level}
        return _orig_uvicorn_run(*args, **kwargs)

    uvicorn.run = _uvicorn_run_with_suppression

    run_server(
        host,
        port,
        not no_reload,
        {"giga_agent": f"{path_part}:{graph_var}"},
        auth={"path": f"giga_agent.modules.auth.langgraph_auth:auth"},
        http={"app": f"{path_part}:{app_var}"},
    )


if __name__ == "__main__":
    app()
