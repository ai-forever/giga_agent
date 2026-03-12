# Observability для локального запуска

Этот раздел описывает настройку трассировки и мониторинга для локального запуска GigaAgent через `pip install` и `giga_agent dev`.

## Обзор

По умолчанию Observability (Phoenix, Langfuse, OpenTelemetry) настроен для Docker-окружения. Для локального запуска необходимо:
- Установить дополнительные зависимости
- Запустить локальный Phoenix сервер (опционально)
- Инструментировать агента в коде
- Настроить переменные окружения

## Содержание

- [Phoenix (Arize AI)](#phoenix-arize-ai)
  - [Установка и запуск локального сервера](#установка-и-запуск-локального-сервера)
  - [Интеграция с агентом](#интеграция-с-агентом)
  - [Использование облачного Phoenix](#использование-облачного-phoenix)
- [Troubleshooting](#troubleshooting)

---

## Phoenix (Arize AI)

[Phoenix](https://phoenix.arize.com/) — open-source платформа для мониторинга и отладки LLM приложений от Arize AI.

### Установка и запуск локального сервера

#### 1. Установка Phoenix

```bash
pip install arize-phoenix
```

#### 2. Запуск сервера

**Вариант A: Python скрипт**

```python
# phoenix_server.py
import phoenix as px

px.launch_app()
```

Запуск:
```bash
python phoenix_server.py
```

**Вариант B: CLI**

```bash
python -m phoenix.server.main serve
```

По умолчанию Phoenix UI будет доступен по адресу: `http://localhost:6006`

### Интеграция с агентом

Для интеграции Phoenix с вашим кастомным агентом нужно:

#### 1. Установить зависимости

Создайте проект с зависимостями:

```toml
# pyproject.toml
[project]
name = "my-agent-with-observability"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "giga-agent",
    "arize-phoenix",
    "openinference-instrumentation-langchain"
]
```

Установка:
```bash
uv sync
# или
pip install giga-agent arize-phoenix openinference-instrumentation-langchain
```

#### 2. Создать агента с инструментацией

Создайте файл `custom/agent.py`:

```python
import os

from giga_agent.agents.giga_agent import GigaAgent
from openinference.instrumentation.langchain import LangChainInstrumentor
from phoenix.otel import register

# Настройка переменных окружения (можно задать через .env)
os.environ.setdefault("PHOENIX_API_KEY", "")  # Пустая строка для локального сервера
os.environ.setdefault("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006/v1/")

# Регистрация tracer provider
tracer_provider = register(
    project_name="my-giga-agent",  # Имя проекта в Phoenix UI
    endpoint=f"{os.environ['PHOENIX_COLLECTOR_ENDPOINT']}traces",
    batch=True  # Батчинг для производительности
)

# Инструментация LangChain
LangChainInstrumentor().instrument(tracer_provider=tracer_provider)

# Создание агента
agent = GigaAgent()

# Экспорт для LangGraph
graph, app = agent.graph, agent.app
```

#### 3. Запуск агента

```bash
uv run giga_agent dev custom.agent:graph:app
```

#### 4. Просмотр трейсов

Откройте в браузере:
```
http://localhost:6006
```

Вы увидите:
- **Traces** — детальные трейсы выполнения агента
- **Projects** — ваш проект (например, "my-giga-agent")
- **Spans** — отдельные операции (tool calls, LLM calls, retrieval и т.д.)

### Использование облачного Phoenix

Если вы используете [Phoenix Cloud](https://app.phoenix.arize.com/), настройте переменные окружения:

```bash
# .env
PHOENIX_API_KEY="your-phoenix-api-key"
PHOENIX_COLLECTOR_ENDPOINT="https://app.phoenix.arize.com/v1/"
```

В коде агента:

```python
import os
from phoenix.otel import register
from openinference.instrumentation.langchain import LangChainInstrumentor

# Переменные будут загружены из .env
tracer_provider = register(
    project_name="production-agent",
    endpoint=f"{os.environ['PHOENIX_COLLECTOR_ENDPOINT']}traces",
    batch=True
)

LangChainInstrumentor().instrument(tracer_provider=tracer_provider)
```

---

## Пример проекта

Полный рабочий пример доступен в репозитории:

```
examples/agent_with_observability/
├── custom/
│   ├── __init__.py
│   └── agent.py          # Агент с Phoenix инструментацией
├── pyproject.toml        # Зависимости
└── README.md             # Инструкция по запуску
```

**Быстрый старт:**

```bash
cd examples/agent_with_observability
uv sync
uv run giga_agent dev custom.agent:graph:app
```

---

## Переменные окружения

| Переменная | Описание | По умолчанию | Обязательная |
|------------|----------|--------------|--------------|
| `PHOENIX_COLLECTOR_ENDPOINT` | URL Phoenix collector endpoint | `http://localhost:6006/v1/` | Да |
| `PHOENIX_API_KEY` | API ключ для Phoenix Cloud | `""` (пусто для локального) | Нет* |

\* **Обязательна для Phoenix Cloud**, не требуется для локального сервера.

---

## Дополнительные ресурсы

- [Phoenix Documentation](https://docs.arize.com/phoenix)
- [OpenInference Instrumentation](https://github.com/Arize-ai/openinference)
- [Пример в репозитории](../../examples/agent_with_observability/)

## Как помочь

Если вы настроили другие платформы observability (Langfuse, Langsmith, OpenTelemetry) для локального запуска, поделитесь вашей конфигурацией через issue или PR!
