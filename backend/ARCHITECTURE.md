# Архитектура проекта Giga Agent

Проект реализован как расширяемый модульный монолит (Modular Monolith) с гибридной средой запуска (Local vs Docker) и поддержкой подключаемых модулей.

## 1. Стратегия хранения данных (Dual-Database Strategy)

Проект абстрагируется от конкретного движка БД через `SQLAlchemy 2.0`. Драйвер выбирается по `GIGA_AGENT_RUNTIME`:

### Локальная разработка (Dev/Test)

- СУБД: SQLite (`sqlite+aiosqlite`).
- Особенности:
  - работает без Docker, хранит данные в файле;
  - JSON-поля хранятся как `JSON` (в SQLite это TEXT-представление);
  - миграции Alembic работают в режиме `render_as_batch`.

### Продакшн / Docker

- СУБД: PostgreSQL (`postgresql+asyncpg`).
- Особенности:
  - используется нативный `JSONB`;
  - строгая типизация и предсказуемое поведение миграций.

### Реализация JSON-полей

Для кросс-БД используется хелпер `JSON_VARIANT()` из `giga_agent.core.db`:

```python
from sqlalchemy.orm import mapped_column
from giga_agent.core.db import Base, JSON_VARIANT

class MyModel(Base):
    __tablename__ = "my_table"
    data = mapped_column(JSON_VARIANT())
```

## 2. Модульная архитектура

Система состоит из core и модулей.

- Встроенные модули находятся в `giga_agent.modules.*` (сейчас: `auth`, `repl`, `image`, `analyze_images`, `search`).
- Пользовательские модули могут быть внешними пакетами.

### Контракт модуля

Модуль наследуется от `BaseModule` и может переопределять:

- `get_api_router()` — API роутер модуля;
- `async get_tools(user, agent)` — tools;
- `async get_instructions(user, agent)` — системные инструкции;
- `get_middleware()` — middleware;
- `on_startup(session)` — startup hook.

`BaseModule` автоматически вычисляет `module_path`, а миграции ищутся по пути `<module_path>/migrations`.

### Роутинг модулей

В `BaseAgent` core-роуты (`connectors`, `llms`, `embeddings`, `sandboxes`, `files`, `generators`, `search-engines`) подключаются автоматически.
Роутер модуля, если он есть, подключается с префиксом `/{module.id}`.

### Core runtime-ресурсы

Core-уровень хранит runtime-конфигурации в отдельных таблицах:
`core_connectors`, `core_llms`, `core_embeddings`, `core_image_generators`, `core_search_engines`.
Для активного выбора пользователем используются nullable-ссылки в `core_users`:
`embedding_id`, `image_generator_id`, `search_engine_id`.

### Пример подключения встроенных модулей

```python
from giga_agent.core.agent.base import BaseAgent
from giga_agent.modules.analyze_images import AnalyzeImagesModule
from giga_agent.modules.auth import AuthModule
from giga_agent.modules.image import ImageModule
from giga_agent.modules.repl import ReplModule
from giga_agent.modules.search import SearchModule

agent = BaseAgent(
    modules=[
        AuthModule(),
        ReplModule(),
        ImageModule(),
        AnalyzeImagesModule(),
        SearchModule(),
    ]
)
app, graph = agent.app, agent.graph
```

### Capability-based tools

Модуль `analyze_images` включает tool `analyze_image` только если активный для пользователя
LLM runtime поддерживает `can_analyze_image()`.

## 3. Управление миграциями

Alembic работает в режиме multiple version locations.

1. CLI собирает пути миграций core + активных модулей.
2. Пути прокидываются в `version_locations` динамически.
3. `upgrade head` применяется единым проходом.

### Миграции модулей (branch + depends_on)

Чтобы миграции модулей не «продвигали» core-цепочку и не привязывались к ней через `down_revision`,
для модулей используется отдельная ветка Alembic:

- **`down_revision`**: всегда `None` (модульные ревизии не продолжают core-историю)
- **`branch_labels`**: `<module_name>` (например, `rag`)
- **`depends_on`**:
  - для первой миграции модуля — текущий head core
  - для последующих — текущий head core (модульная история продолжается через `down_revision=<предыдущая миграция модуля>`)

Дополнительно:

- `giga_agent check` проверяет конфликтующие heads;
- `giga_agent makemigrations <agent_path> [module_import_path] ...` создаёт миграции для конкретного модуля (если указан `module_import_path`) или для всех модулей, подключённых в агенте, с фильтром по табличному префиксу;
- для core-моделей используется `make core-migrations` (или `giga_agent makemigrations --core`, но это dev-only путь).

## 4. Запуск и lifecycle

Актуальная команда запуска в разработке: `giga_agent dev`.

Пайплайн `giga_agent dev`:

1. Поднимает runtime-конфиг (`GIGA_AGENT_RUNTIME=local` по умолчанию).
2. Загружает graph/app из указанного entrypoint.
3. Применяет миграции core + модулей.
4. Выполняет `on_startup()` для всех модулей.
5. Запускает LangGraph/FastAPI сервер.

## 5. Правила текущей разработки

- Удаляй неиспользуемые классы и мёртвый код, не оставляй заглушки «на потом».
- Используй `uv` для локальных команд (test/lint/run/migrations).
