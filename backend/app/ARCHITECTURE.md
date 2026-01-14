# Архитектура проекта Giga Agent

Проект спроектирован как расширяемый модульный монолит (Modular Monolith) с поддержкой гибридной среды запуска (Local vs Docker) и возможностью подключения пользовательских плагинов (External Modules).

## 1. Стратегия хранения данных (Dual-Database Strategy)

Проект абстрагируется от конкретного движка БД, используя `SQLAlchemy 2.0`. Драйвер и диалект выбираются автоматически в зависимости от среды:

### Локальная разработка (Dev/Test)
*   **СУБД:** SQLite (`sqlite+aiosqlite`).
*   **Особенности:**
    *   Работает без Docker, хранит данные в файле.
    *   Тип `JSONB` эмулируется через `TEXT` (SQLAlchemy прозрачно сериализует/десериализует словари).
    *   Миграции Alembic работают в режиме `render_as_batch` (обход ограничений SQLite на ALTER TABLE).

### Продакшн / Docker
*   **СУБД:** PostgreSQL (`postgresql+asyncpg`).
*   **Особенности:**
    *   Используется нативный бинарный тип `JSONB` для высокой производительности.
    *   Строгая типизация и надежность.

### Реализация моделей
Для кросс-платформенности JSON-полей используется метод `with_variant`:

from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB

В Postgres это JSONB, в SQLite — TEXT (JSON)
data = mapped_column(JSON().with_variant(JSONB, "postgresql"))## 2. Модульная архитектура и Плагины

Система состоит из ядра и модулей. Модули могут быть встроенными (`giga_agent/auth`) или внешними (пользовательскими).

### Структура модуля
Каждый модуль (встроенный или внешний) должен следовать единой структуре и наследоваться от базового класса, чтобы система могла найти его миграции.
```
my_module/
├── migrations/        # Папка с версиями миграций Alembic для этого модуля
├── __init__.py
├── module.py          # Основной класс модуля
└── models.py          # SQLAlchemy модели### Подключение пользовательских модулей
```
Пользователи могут создавать свои модули, не меняя код ядра. Инициализация происходит через передачу экземпляров модулей в конструктор агента:
user_project/agent.py
```python
from giga_agent.agent import Agent
from my_custom_module import CustomAuthModule

agent = Agent(
    modules=[CustomAuthModule()]
)
```
## 3. Управление миграциями (Dynamic Alembic Configuration)
Alembic настроен на работу с множеством источников миграций (Multiple Version Locations).

1.  **Сбор путей:** При старте CLI анализирует список подключенных модулей.
2.  **Инъекция:** Пути к папкам `migrations` каждого модуля собираются и динамически передаются в конфигурацию Alembic (параметр `version_locations`) в runtime.
3.  **Применение:** Команда `upgrade head` применяет миграции и ядра, и всех плагинов единым проходом.

Для удобства разработки CLI должен предоставлять команду для создания миграций в нужном модуле:
`giga_agent makemigrations --module=path/to/module "message"`

## 4. Жизненный цикл и Запуск (`giga_agent up`)

Запуск проекта осуществляется единой CLI командой, которая оркестрирует весь процесс инициализации.

**Алгоритм работы `giga_agent up`:**

1.  **Wait-for-DB (Только для Docker/Postgres):**
    *   Запускает цикл проверки доступности порта БД.
    *   Предотвращает падение приложения при "холодном старте", когда контейнер приложения поднимается быстрее базы данных.
2.  **Dynamic Migrations:**
    *   Считывает конфигурацию агента.
    *   Программно запускает `alembic upgrade head`, накатывая актуальную схему.
3.  **Application Start:**
    *   Запускает основное приложение (API/Worker).

## 5. Пример реализации базового класса модуля
```python
import os
import inspect

class BaseModule:
    def __init__(self):
        # Автоматически определяем путь к файлу модуля
        self.module_path = os.path.dirname(inspect.getfile(self.__class__))

    @property
    def migration_path(self) -> str | None:
        """Абсолютный путь к папке миграций модуля, если она существует"""
        path = os.path.join(self.module_path, "migrations")
        if os.path.exists(path) and os.path.isdir(path):
            return path
        return None
```

При создании агента через create_agent в langchain на каждый middleware в получающемся графе 
создается отдельная нода. 
Если мы хотим, чтобы модули можно было отключать у отдельных агентов, то нужно будет 
переделать эту логику, чтобы ноды before_agent, after_agent и т.д. были уже созданы и 
внутри них мы бы проходились по ним и делали merge стейтам.
