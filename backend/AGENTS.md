# AGENTS.md (backend/app)

Этот файл задаёт рабочие правила для изменений в `/Users/mikelarg/PycharmProjects/giga_agent/backend/app`.

## 0. Базовые правила разработки

- Проект в активной ранней разработке: не оставляй мёртвый код и пустые классы «на будущее», если они больше не нужны.
- Для запуска команд используй `uv`.

## 1. Текущее устройство пакета

- Основной пакет: `giga_agent`.
- Встроенные модули: `giga_agent.modules.auth`, `giga_agent.modules.repl`, `giga_agent.modules.image`, `giga_agent.modules.analyze_images`, `giga_agent.modules.search`.
- Базовый агент: `giga_agent.core.agent.base.BaseAgent`.
- Базовый модуль: `giga_agent.core.module.BaseModule`.
- Core API роуты подключаются автоматически: `connectors`, `llms`, `embeddings`, `sandboxes`, `files`, `generators`, `search-engines`.
- Роуты модулей подключаются автоматически с префиксом `/{module.id}`.

## 2. Команды разработки

- Запуск dev-сервера:
  - `uv run giga_agent dev`
  - `uv run giga_agent dev giga_agent.agents.run:graph:app`
- Тесты:
  - `uv run pytest`
- Линт/формат:
  - `uv run ruff check .`
  - `uv run ruff format .`
- Миграции руками не пишем — генерируем командами ниже.
- Создание миграции core-моделей:
  - `make core-migrations m="message"`
  - `uv run giga_agent makemigrations giga_agent.agents.run:agent --core -m "message"` (dev-only; увидишь warning)
- Создание миграции модуля:
  - `uv run giga_agent makemigrations giga_agent.agents.run:agent giga_agent.modules.auth -m "message"`
  - `uv run giga_agent makemigrations` (для всех модулей, подключённых в агенте)
- Проверка migration heads:
  - `uv run giga_agent check`
  - `uv run giga_agent check --agent-path giga_agent.agents.run:agent`
- Проксирование любых Alembic команд с подгрузкой модулей агента:
  - `uv run giga_agent alembic upgrade head`
  - `uv run giga_agent alembic --scope rag current`
  - `uv run giga_agent alembic --agent-path giga_agent.agents.run:agent upgrade head`

## 2.1. Политика миграций модулей

- Core использует `alembic_version`.
- Каждый модуль использует отдельную таблицу `alembic_version_<module.id>`.
- Модульные миграции образуют независимую линейную цепочку:
 - первая миграция модуля: `down_revision=None`, без `depends_on`, без `branch_labels`;
 - последующие миграции модуля: `down_revision=<предыдущая миграция модуля>`.
- Порядок применения обеспечивает раннер: сначала `core`, затем активные модули агента.
- Для low-level Alembic операций scope выбирается через `--scope core|<module.id>`.

## 3. Правила по модулям

- Каждый модуль должен наследоваться от `BaseModule` и иметь уникальный `id`.
- Миграции модуля должны лежать в `<module_path>/migrations`.
- Если модуль добавляет API, возвращай `APIRouter` в `get_api_router()` без ручного префикса модуля.
- Если модуль добавляет инструменты, используй `async get_tools(user, agent)`.
- Если модуль добавляет системные инструкции, используй `async get_instructions(user, agent)`.
- Если модуль требует startup-инициализацию, используй `on_startup(session)`.
- Для получения пользователя из `config`/`runtime.config` **не обращайся к словарю напрямую** (`config["configurable"]["langgraph_auth_user"]["identity"]`). В Aegra `langgraph_auth_user` приходит как `BaseModel`, а не `dict`, — прямой доступ по ключу упадёт. Используй хелперы из `giga_agent.utils.langgraph_sdk`:
  - `get_user_id_from_config(config)` — вернёт `identity` (обычно строка UUID; оборачивай в `uuid.UUID(...)` при необходимости);
  - `get_user_value_from_config(config, "<field>")` — для остальных полей (`token` и т.п.).
  - Оба хелпера уже корректно разбирают и `BaseModel`, и `dict`.

## 4. База данных и модели

- Для JSON-полей используй `JSON_VARIANT()` из `giga_agent.core.db`.
- Core-модели живут в `giga_agent.models.*` и используют явный префикс `core_`.
- Для модульных моделей автопрефикс таблиц берётся из пути модуля (например, `giga_agent.modules.auth.models` -> `auth_*`).
- Не ломай совместимость миграций со SQLite (`render_as_batch` в Alembic env).

## 5. Синхронизация документации

При архитектурных изменениях обновляй синхронно:

- `/Users/mikelarg/PycharmProjects/giga_agent/backend/app/AGENTS.md`
- `/Users/mikelarg/PycharmProjects/giga_agent/backend/app/ARCHITECTURE.md`
- `/Users/mikelarg/PycharmProjects/giga_agent/backend/app/Makefile` и `/Users/mikelarg/PycharmProjects/giga_agent/backend/app/giga_agent/agents/run.py` (если меняются команды/entrypoints)
