# Environment Variables Reference

Полный справочник переменных окружения для настройки GigaAgent.

## Содержание

- [Environment Variables Reference](#environment-variables-reference)
  - [Содержание](#содержание)
  - [Основные настройки](#основные-настройки)
  - [Аутентификация и безопасность](#аутентификация-и-безопасность)
  - [База данных и runtime](#база-данных-и-runtime)
  - [UI и API](#ui-и-api)
  - [LangGraph Dev Server](#langgraph-dev-server)
  - [Local Docker Sandbox](#local-docker-sandbox)
    - [Основные настройки](#основные-настройки-1)
    - [Ограничения ресурсов](#ограничения-ресурсов)
    - [Безопасность](#безопасность)
  - [Sandbox Lifecycle Management](#sandbox-lifecycle-management)
    - [Idle Sweeper](#idle-sweeper)
    - [Orphan Sweeper](#orphan-sweeper)
  - [Интеграции](#интеграции)
    - [Qdrant и Mem0](#qdrant-и-mem0)
    - [Web Scraper (Jina)](#web-scraper-jina)
  - [Миграции и логирование](#миграции-и-логирование)
  - [Инструменты](#инструменты)
  - [Observability](#observability)
    - [Phoenix](#phoenix)
    - [Langfuse](#langfuse)
    - [OpenTelemetry](#opentelemetry)
  - [Быстрый старт: Минимальная конфигурация](#быстрый-старт-минимальная-конфигурация)
    - [Для local dev (pip install)](#для-local-dev-pip-install)
    - [Для Docker deployment](#для-docker-deployment)
    - [Для production](#для-production)
  - [Troubleshooting](#troubleshooting)
    - [Проблема: SECRET\_KEY не задан](#проблема-secret_key-не-задан)
    - [Проблема: Local Docker sandbox не работает](#проблема-local-docker-sandbox-не-работает)

---

## Основные настройки

Базовые параметры конфигурации системы.

| Переменная | Тип | По умолчанию | Обязательная | Описание |
|------------|-----|--------------|--------------|----------|
| `GIGA_AGENT_RUNTIME` | `str` | `local` | Нет | Режим запуска: `local` (SQLite) или `docker` (PostgreSQL) |
| `GIGA_AGENT_PROJECT_ROOT` | `Path` | `./.giga_agent` | Нет | Корневая директория для локальных файлов проекта |
| `GIGA_AGENT_HOST` | `str` | `None` | Нет | Host для binding сервера |
| `GIGA_AGENT_PORT` | `str` | `None` | Нет | Порт для сервера |
| `GIGA_AGENT_LOG_LEVEL` | `str` | `INFO` | Нет | Уровень логирования: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `GIGA_AGENT_LOG_FORMAT` | `str` | `None` | Нет | Формат логов (если не задан, используется дефолтный) |
| `GIGA_AGENT_LOG_JSON` | `bool` | `False` | Нет | Включить JSON-формат логов |

---

## Аутентификация и безопасность

Настройки для JWT-аутентификации и первичной инициализации администратора.

| Переменная | Тип | По умолчанию | Обязательная | Описание |
|------------|-----|--------------|--------------|----------|
| `GIGA_AGENT_SECRET_KEY` | `str` | `None` | **Да (production)** | 🔒 Секретный ключ для подписи JWT токенов. **Обязателен для production!** |
| `GIGA_AGENT_AUTH_ALGORITHM` | `str` | `HS256` | Нет | Алгоритм для JWT (HS256, RS256 и т.д.) |
| `GIGA_AGENT_ADMIN_EMAIL` | `str` | `admin@example.com` | Нет | Email администратора при первой инициализации (когда БД пуста) |
| `GIGA_AGENT_ADMIN_PASSWORD` | `str` | `giga_agent_admin` | Нет | Пароль администратора при первой инициализации |

> **⚠️ ВАЖНО для production:**
> - Обязательно задайте уникальный `GIGA_AGENT_SECRET_KEY` (минимум 32 символа)
> - Смените дефолтные `GIGA_AGENT_ADMIN_EMAIL` и `GIGA_AGENT_ADMIN_PASSWORD`
> - После первого запуска admin-креды применяются только если в БД нет пользователей

---

## База данных и runtime

Настройки подключения к базе данных.

| Переменная | Тип | По умолчанию | Обязательная | Описание |
|------------|-----|--------------|--------------|----------|
| `GIGA_AGENT_DATABASE_URL` | `str` | `None` | Нет | Строка подключения к БД. Если не задано, используется SQLite в `PROJECT_ROOT` |
| `GIGA_AGENT_DOCKER_NETWORK` | `str` | `None` | Нет | Docker network для sandbox-контейнеров (если используется local docker) |
| `GIGA_AGENT_HOST_PROJECT_PATH` | `Path` | `None` | Нет* | Абсолютный путь к репозиторию на хост-машине. **Обязателен для local docker sandbox** |

**Примеры DATABASE_URL:**
```bash
# SQLite (local dev)
GIGA_AGENT_DATABASE_URL="sqlite+aiosqlite:///.giga_agent/giga_agent.db"

# PostgreSQL (production)
GIGA_AGENT_DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/giga_agent"
```

---

## UI и API

Настройки веб-интерфейса и API endpoints.

| Переменная | Тип | По умолчанию | Обязательная | Описание |
|------------|-----|--------------|--------------|----------|
| `GIGA_AGENT_UI` | `bool` | `True` | Нет | Включить/выключить раздачу UI через FastAPI |
| `GIGA_AGENT_FRONTEND_DIR` | `str` | `None` | Нет | Путь к директории с собранным frontend (если не задано, используется встроенный) |
| `GIGA_AGENT_UI_PREFIX` | `str` | `None` | Нет | Префикс для UI роутов (если нужно отличие от корня) |
| `GIGA_AGENT_PREFIX_API` | `str` | `/agent` | Нет | Префикс для API endpoints |

**Примеры:**
```bash
# API будет доступно по /agent/*, UI по /
GIGA_AGENT_PREFIX_API="/agent"
GIGA_AGENT_UI=true

# Кастомная директория frontend
GIGA_AGENT_FRONTEND_DIR="/path/to/custom/dist"
```

---

## LangGraph Dev Server

Настройки для LangGraph dev-сервера (используется при `giga_agent dev`).

| Переменная | Тип | По умолчанию | Обязательная | Описание |
|------------|-----|--------------|--------------|----------|
| `GIGA_AGENT_LANGGRAPH_API_URL` | `str` | `None` | Нет | URL LangGraph API (если используется внешний LangGraph сервер) |
| `GIGA_AGENT_LANGGRAPH_DEV_UVICORN_APP` | `str` | `None` | Нет | Uvicorn app для dev-режима |
| `GIGA_AGENT_LANGGRAPH_DEV_HOST` | `str` | `127.0.0.1` | Нет | Host для dev-сервера |
| `GIGA_AGENT_LANGGRAPH_DEV_PORT` | `int` | `9090` | Нет | Порт для dev-сервера |
| `GIGA_AGENT_LANGGRAPH_DEV_RELOAD` | `bool` | `True` | Нет | Включить hot-reload в dev-режиме |
| `GIGA_AGENT_LANGGRAPH_DEV_GRAPHS_JSON` | `str` | `{}` | Нет | JSON с конфигурацией графов |
| `GIGA_AGENT_LANGGRAPH_DEV_AUTH_PATH` | `str` | `""` | Нет | Путь к auth module для LangGraph |
| `GIGA_AGENT_LANGGRAPH_DEV_HTTP_APP` | `str` | `""` | Нет | HTTP app для LangGraph |
| `GIGA_AGENT_LANGGRAPH_DEV_HTTP_CONFIG_JSON` | `str` | `None` | Нет | JSON конфигурация HTTP для LangGraph |

---

## Local Docker Sandbox

Настройки для провайдера `local_docker` — выполнение кода в локальных Docker-контейнерах.

> **Примечание:** Local Docker sandbox доступен только для superuser'ов в целях безопасности.

### Основные настройки

| Переменная | Тип | По умолчанию | Обязательная | Описание |
|------------|-----|--------------|--------------|----------|
| `GIGA_AGENT_LOCAL_SANDBOX_ENABLED` | `bool` | `True` | Нет | Включить/выключить local docker sandbox |
| `GIGA_AGENT_LOCAL_DOCKER_IMAGE` | `str` | `mikelarg/code-interpreter:0.0.5` | Нет | Docker образ для sandbox-контейнеров |
| `GIGA_AGENT_LOCAL_DOCKER_MAX_ACTIVE_SANDBOXES` | `int` | `3` | Нет | Максимальное количество одновременно работающих sandbox'ов |
| `GIGA_AGENT_LOCAL_DOCKER_STARTUP_TIMEOUT_SEC` | `int` | `20` | Нет | Таймаут запуска контейнера (секунды) |
| `GIGA_AGENT_LOCAL_DOCKER_FILES_PATH` | `Path` | `None` | Нет | Путь для хранения файлов sandbox'ов |

### Ограничения ресурсов

| Переменная | Тип | По умолчанию | Описание |
|------------|-----|--------------|----------|
| `GIGA_AGENT_LOCAL_DOCKER_MEMORY_LIMIT_MB` | `int` | `512` | Лимит памяти для контейнера (МБ) |
| `GIGA_AGENT_LOCAL_DOCKER_MEMORY_RESERVATION_MB` | `int` | `512` | Резервирование памяти (МБ) |
| `GIGA_AGENT_LOCAL_DOCKER_VCPU` | `float` | `0.3` | CPU квота (доля vCPU) |
| `GIGA_AGENT_LOCAL_DOCKER_PIDS_LIMIT` | `int` | `256` | Максимальное количество процессов |
| `GIGA_AGENT_LOCAL_DOCKER_SHM_SIZE_MB` | `int` | `128` | Размер /dev/shm (МБ) |
| `GIGA_AGENT_LOCAL_DOCKER_NOFILE_SOFT` | `int` | `1024` | Soft limit открытых файлов |
| `GIGA_AGENT_LOCAL_DOCKER_NOFILE_HARD` | `int` | `4096` | Hard limit открытых файлов |

### Безопасность

| Переменная | Тип | По умолчанию | Описание |
|------------|-----|--------------|----------|
| `GIGA_AGENT_LOCAL_DOCKER_READONLY_ROOTFS` | `bool` | `False` | Сделать root filesystem read-only |

**Пример конфигурации:**
```bash
GIGA_AGENT_LOCAL_SANDBOX_ENABLED=true
GIGA_AGENT_LOCAL_DOCKER_IMAGE="mikelarg/code-interpreter:0.0.5"
GIGA_AGENT_LOCAL_DOCKER_MEMORY_LIMIT_MB=1024
GIGA_AGENT_LOCAL_DOCKER_VCPU=0.5
GIGA_AGENT_LOCAL_DOCKER_MAX_ACTIVE_SANDBOXES=5
GIGA_AGENT_HOST_PROJECT_PATH="/absolute/path/to/giga_agent"
```

---

## Sandbox Lifecycle Management

Настройки для фоновых процессов управления жизненным циклом sandbox'ов.

### Idle Sweeper

Останавливает неактивные sandbox'ы после таймаута.

| Переменная | Тип | По умолчанию | Описание |
|------------|-----|--------------|----------|
| `GIGA_AGENT_SANDBOX_IDLE_SWEEPER_ENABLED` | `bool` | `True` | Включить idle sweeper |
| `GIGA_AGENT_SANDBOX_IDLE_SWEEPER_INTERVAL_SEC` | `int` | `60` | Интервал проверки (секунды, минимум 10) |
| `GIGA_AGENT_SANDBOX_IDLE_SWEEPER_LOCK_KEY` | `str` | `sandbox:idle-cleanup:lock` | Redis ключ для distributed lock |
| `GIGA_AGENT_SANDBOX_IDLE_SWEEPER_LOCK_TTL_SEC` | `int` | `55` | TTL для lock (секунды, минимум 5) |
| `GIGA_AGENT_SANDBOX_STARTING_TTL_SEC` | `int` | `120` | Таймаут для sandbox'ов в статусе "starting" (секунды, минимум 10) |

### Orphan Sweeper

Очищает "осиротевшие" внешние ресурсы (контейнеры без записи в БД).

| Переменная | Тип | По умолчанию | Описание |
|------------|-----|--------------|----------|
| `GIGA_AGENT_SANDBOX_ORPHAN_SWEEPER_ENABLED` | `bool` | `True` | Включить orphan sweeper |
| `GIGA_AGENT_SANDBOX_ORPHAN_SWEEPER_INTERVAL_SEC` | `int` | `120` | Интервал проверки (секунды, минимум 10) |
| `GIGA_AGENT_SANDBOX_ORPHAN_SWEEPER_LOCK_KEY` | `str` | `sandbox:orphan-cleanup:lock` | Redis ключ для distributed lock |
| `GIGA_AGENT_SANDBOX_ORPHAN_SWEEPER_LOCK_TTL_SEC` | `int` | `110` | TTL для lock (секунды, минимум 5) |
| `GIGA_AGENT_SANDBOX_ORPHAN_SWEEPER_CONCURRENCY` | `int` | `1` | Количество одновременных cleanup задач (минимум 1) |

> **Примечание:** Sweeper'ы используют Redis для координации между инстансами в multi-instance deployment.

---

## Интеграции

### Qdrant и Mem0

Настройки для векторного хранилища и долговременной памяти.

| Переменная | Тип | По умолчанию | Описание |
|------------|-----|--------------|----------|
| `GIGA_AGENT_QDRANT_POOL_SIZE` | `int` | `None` | Размер connection pool для Qdrant |
| `GIGA_AGENT_MEM0_QDRANT_ENSURE_CACHE` | `bool` | `True` | Обеспечить кэширование для Mem0 в Qdrant |

**Внешние переменные (из Qdrant/Mem0):**
```bash
# Qdrant connection
QDRANT_URL="http://localhost:6333"
QDRANT_API_KEY="your-api-key"
```

### Web Scraper (Jina)

Настройки для модуля веб-скрапинга через Jina AI Reader.

| Переменная | Тип | По умолчанию | Описание |
|------------|-----|--------------|----------|
| `GIGA_AGENT_SCRAPER_JINA_BASE_URL` | `str` | `https://r.jina.ai/` | Base URL для Jina Reader API |
| `GIGA_AGENT_SCRAPER_TOTAL_CONCURRENCY` | `int` | `8` | Максимальное количество одновременных запросов (минимум 1) |

---

## Миграции и логирование

Настройки для Alembic миграций и startup процесса.

| Переменная | Тип | По умолчанию | Описание |
|------------|-----|--------------|----------|
| `GIGA_AGENT_SKIP_STARTUP_MIGRATIONS` | `bool` | `False` | Пропустить автоматические миграции при старте |
| `GIGA_AGENT_ALEMBIC_FILECONFIG` | `bool` | `False` | Использовать файловую конфигурацию Alembic (alembic.ini) |
| `GIGA_AGENT_STARTUP_MIGRATIONS_LOCK_KEY` | `str` | `startup:migrations:lock` | Redis ключ для lock при миграциях |
| `GIGA_AGENT_STARTUP_MIGRATIONS_LOCK_TTL_SEC` | `int` | `1800` | TTL для migration lock (секунды, минимум 5) |

> **Рекомендация:** В production с несколькими инстансами НЕ отключайте миграции на старте. Distributed lock через Redis обеспечивает безопасное применение миграций только одним инстансом.

---

## Инструменты

Общие настройки для инструментов агента.

| Переменная | Тип | По умолчанию | Описание |
|------------|-----|--------------|----------|
| `GIGA_AGENT_TOOL_MAX_SIZE` | `int` | `25000` | Максимальный размер результата tool (символы) |

---

## Observability

Настройки для трассировки и мониторинга через Phoenix/Langfuse/OTLP. 

> **Примечание:** Эти переменные применяются в Docker-окружении. Для настройки Observability в локальном запуске см. [observability-local.md](observability-local.md).

### Phoenix

```bash
# Phoenix Arize трассировка
PHOENIX_COLLECTOR_ENDPOINT="http://localhost:4318/v1/traces"
PHOENIX_API_KEY="your-phoenix-api-key"
```

### Langfuse

```bash
# Langfuse трассировка
LANGFUSE_PUBLIC_KEY="pk-..."
LANGFUSE_SECRET_KEY="sk-..."
LANGFUSE_HOST="https://cloud.langfuse.com"
```

### OpenTelemetry

```bash
# Список целей для OTEL трассировки (через запятую)
OTEL_TARGETS="PHOENIX,LANGFUSE"

# Generic OTLP endpoint
OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4318"
OTEL_EXPORTER_OTLP_HEADERS="x-api-key=your-key"
```

---

## Быстрый старт: Минимальная конфигурация

### Для local dev (pip install)

```bash
# Не требуется дополнительная конфигурация!
# Все работает из коробки с дефолтными значениями
giga_agent run dev
```

### Для Docker deployment

Минимальный `.env`:

```bash
# Обязательно
GIGA_AGENT_SECRET_KEY="your-super-secret-key-min-32-chars"
GIGA_AGENT_HOST_PROJECT_PATH="/absolute/path/to/giga_agent"

# Настоятельно рекомендуется
GIGA_AGENT_ADMIN_EMAIL="admin@your-domain.com"
GIGA_AGENT_ADMIN_PASSWORD="strong-password-here"
```

### Для production

```bash
# Секретность
GIGA_AGENT_SECRET_KEY="production-secret-key-min-32-chars-random"
GIGA_AGENT_ADMIN_EMAIL="admin@company.com"
GIGA_AGENT_ADMIN_PASSWORD="VeryStr0ng!Pass"

# Runtime
GIGA_AGENT_RUNTIME="docker"
GIGA_AGENT_DATABASE_URL="postgresql+asyncpg://user:pass@postgres:5432/giga_agent"

# Observability (опционально)
PHOENIX_COLLECTOR_ENDPOINT="https://your-phoenix.com/v1/traces"
PHOENIX_API_KEY="your-key"
OTEL_TARGETS="PHOENIX"
```

## Troubleshooting

### Проблема: SECRET_KEY не задан

**Симптомы:** Ошибка при старте или некорректная работа JWT.

**Решение:**
```bash
# Сгенерируйте безопасный ключ
python -c "import secrets; print(secrets.token_urlsafe(32))"

# Добавьте в .env
GIGA_AGENT_SECRET_KEY="generated-key-here"
```

### Проблема: Local Docker sandbox не работает

**Симптомы:** Ошибка при создании sandbox'а, timeout.

**Проверьте:**
1. Docker daemon запущен: `docker ps`
2. `GIGA_AGENT_HOST_PROJECT_PATH` задан корректно (абсолютный путь)
3. Docker network существует (если `GIGA_AGENT_DOCKER_NETWORK` задан)
4. Пользователь является superuser
