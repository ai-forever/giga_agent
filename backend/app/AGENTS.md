# AGENTS.md (backend/app)

Этот файл задаёт рабочие правила для изменений в `/Users/mikelarg/PycharmProjects/giga_agent/backend/app`.

## 0. Базовые правила разработки

- Проект в активной ранней разработке: не оставляй мёртвый код и пустые классы «на будущее», если они больше не нужны.
- Для запуска команд используй `uv`.

## 1. Текущее устройство пакета

- Основной пакет: `giga_agent`.
- Встроенные модули: `giga_agent.modules.auth`, `giga_agent.modules.repl`, `giga_agent.modules.image`, `giga_agent.modules.search`.
- Базовый агент: `giga_agent.core.agent.base.BaseAgent`.
- Базовый модуль: `giga_agent.core.module.BaseModule`.
- Core API роуты подключаются автоматически: `connectors`, `llms`, `embeddings`, `sandboxes`, `files`, `generators`, `search-engines`.
- Роуты модулей подключаются автоматически с префиксом `/{module.id}`.

## 2. Команды разработки

- Запуск dev-сервера:
  - `uv run giga_agent dev agent_test/agent.py:graph:app`
- Тесты:
  - `uv run pytest`
- Линт/формат:
  - `uv run ruff check .`
  - `uv run ruff format .`
- Миграции руками не пишем — генерируем командами ниже.
- Создание миграции core-моделей:
  - `make core-migrations m="message"`
- Создание миграции модуля:
  - `uv run giga_agent makemigrations agent_test/agent.py:agent giga_agent.modules.auth -m "message"`
  - `uv run giga_agent makemigrations agent_test/agent.py:agent` (для всех модулей, подключённых в агенте)
- Проверка migration heads:
  - `uv run giga_agent check --agent-path agent_test/agent.py:agent`
- Проксирование любых Alembic команд с подгрузкой модулей агента:
  - `uv run giga_agent alembic --agent-path agent_test/agent.py:agent upgrade head`

## 2.1. Политика миграций модулей

- Модульные миграции генерируются как отдельные ветки Alembic: `branch_labels=<module_name>`.
- Для модулей **не используется** `down_revision` (он всегда `None`).
- Порядок применения обеспечивается через `depends_on`:
  - первая миграция модуля зависит от текущего head core;
  - последующие миграции модуля зависят от предыдущей миграции этого модуля.

## 3. Правила по модулям

- Каждый модуль должен наследоваться от `BaseModule` и иметь уникальный `id`.
- Миграции модуля должны лежать в `<module_path>/migrations`.
- Если модуль добавляет API, возвращай `APIRouter` в `get_api_router()` без ручного префикса модуля.
- Если модуль добавляет инструменты, используй `async get_tools(user, agent)`.
- Если модуль добавляет системные инструкции, используй `async get_instructions(user, agent)`.
- Если модуль требует startup-инициализацию, используй `on_startup(session)`.

## 4. База данных и модели

- Для JSON-полей используй `JSON_VARIANT()` из `giga_agent.core.db`.
- Core-модели живут в `giga_agent.models.*` и используют явный префикс `core_`.
- Для модульных моделей автопрефикс таблиц берётся из пути модуля (например, `giga_agent.modules.auth.models` -> `auth_*`).
- Не ломай совместимость миграций со SQLite (`render_as_batch` в Alembic env).

## 5. Синхронизация документации

При архитектурных изменениях обновляй синхронно:

- `/Users/mikelarg/PycharmProjects/giga_agent/backend/app/AGENTS.md`
- `/Users/mikelarg/PycharmProjects/giga_agent/backend/app/ARCHITECTURE.md`
- `/Users/mikelarg/PycharmProjects/giga_agent/backend/app/Makefile` и `/Users/mikelarg/PycharmProjects/giga_agent/backend/app/agent_test/agent.py` (если меняются команды/entrypoints)
