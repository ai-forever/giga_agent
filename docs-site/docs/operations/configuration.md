---
title: "Конфигурация"
description: "Переменные окружения и значения по умолчанию для GigaAgent в текущей ветке main."
---

# Конфигурация

:::info[Документация текущего состояния]
Эта страница описывает текущую ветку `main` репозитория GigaAgent. Для стабильной документации PyPI-пакета `giga-agent==0.1.9` выберите версию **0.1.9 (PyPI)** в переключателе версий.
:::

Эта страница описывает основные переменные окружения текущей ветки `main`. Названия переменных оставлены без перевода, потому что они используются в командах и файлах окружения.

## Базовые настройки

| Переменная | Значение по умолчанию | Назначение |
|---|---:|---|
| `GIGA_AGENT_PREFIX_API` | `/agent` | Внутренний префикс маршрутов GigaAgent. При запуске через `giga_agent dev` внешний путь обычно начинается с `/api/agent`. |
| `GIGA_AGENT_BASE_URL` | пусто | Публичный базовый адрес, если интерфейс должен строить ссылки не от текущего домена. |
| `GIGA_AGENT_FRONTEND_DIR` | пусто | Переопределение каталога веб-интерфейса. Обычно не требуется. |
| `GIGA_AGENT_UI` | `true` | Включает отдачу веб-интерфейса серверной частью. |
| `GIGA_AGENT_UI_PREFIX` | пусто | Префикс веб-интерфейса, если он размещается не в корне. |
| `GIGA_AGENT_RUNTIME` | `local` | Режим выполнения. |
| `GIGA_AGENT_RUNTIME_LOCAL` | `false` | Признак локального режима для рабочей конфигурации интерфейса. |
| `GIGA_AGENT_DATABASE_URL` | пусто | Адрес базы данных SQLAlchemy; без переопределения используется локальная SQLite-база. |
| `GIGA_AGENT_PROJECT_ROOT` | `cwd/.giga_agent` | Рабочий каталог данных GigaAgent. |
| `GIGA_AGENT_HOST_PROJECT_PATH` | пусто | Путь на машине для сценариев с локальной изолированной средой. |
| `GIGA_AGENT_SECRET_KEY` | пусто | Секретный ключ авторизации. Для общего сервера задавайте явно. |
| `GIGA_AGENT_ADMIN_EMAIL` | `admin@example.com` | Почта начального администратора. |
| `GIGA_AGENT_ADMIN_PASSWORD` | `giga_agent_admin` | Пароль начального администратора. |
| `GIGA_AGENT_LANGGRAPH_DEV_HOST` | `127.0.0.1` | Адрес, на котором слушает сервер разработки. |
| `GIGA_AGENT_LANGGRAPH_DEV_PORT` | `9090` | Порт сервера разработки. |
| `GIGA_AGENT_SKIP_ONBOARDING` | `false` | Управляет показом начальной настройки. |
| `GIGA_AGENT_SKIP_STARTUP_MIGRATIONS` | `false` | Если `true`, миграции не запускаются при старте. |

## Ограничения инструментов

| Переменная | Значение по умолчанию | Назначение |
|---|---:|---|
| `GIGA_AGENT_TOOL_MAX_SIZE` | `25000` | Максимальный размер результата инструмента. |
| `GIGA_AGENT_ENABLE_THINK_TOOL` | `true` | Включает служебный инструмент `think`, если выбранный провайдер разрешён. |
| `GIGA_AGENT_ENABLE_MULTI_TOOL_USE` | `true` | Включает параллельное использование инструментов, если выбранный провайдер разрешён. |
| `GIGA_AGENT_GIGACHAT_FROM_ENV` | `false` | Разрешает брать параметры GigaChat из окружения. |
| `GIGA_AGENT_GIGACHAT_SKIP_CACHE_TOKEN` | `false` | Управляет кэшированием токена GigaChat. |

## RAG, память и поиск

| Переменная | Значение по умолчанию | Назначение |
|---|---:|---|
| `GIGA_AGENT_SCRAPER_JINA_BASE_URL` | `https://r.jina.ai/` | Базовый адрес сервиса чтения веб-страниц. |
| `GIGA_AGENT_SCRAPER_TOTAL_CONCURRENCY` | `3` | Общий предел параллельных запросов чтения. |
| `GIGA_AGENT_SCRAPER_DISABLED` | `false` | Отключает инструмент чтения веб-страниц. |
| `QDRANT_URL` | внешний параметр | Адрес Qdrant для RAG и памяти. |
| `GIGA_AGENT_QDRANT_POOL_SIZE` | пусто | Размер пула клиента Qdrant. |
| `GIGA_AGENT_MEM0_QDRANT_ENSURE_CACHE` | `true` | Настройка кэша для памяти и Qdrant. |

## Изолированная среда

| Переменная | Значение по умолчанию |
|---|---:|
| `GIGA_AGENT_LOCAL_SANDBOX_ENABLED` | `true` |
| `GIGA_AGENT_LOCAL_DOCKER_IMAGE` | `mikelarg/code-interpreter:0.0.5` |
| `GIGA_AGENT_LOCAL_DOCKER_MEMORY_LIMIT_MB` | `2048` |
| `GIGA_AGENT_LOCAL_DOCKER_MEMORY_RESERVATION_MB` | `512` |
| `GIGA_AGENT_LOCAL_DOCKER_VCPU` | `1.0` |
| `GIGA_AGENT_LOCAL_DOCKER_PIDS_LIMIT` | `256` |
| `GIGA_AGENT_LOCAL_DOCKER_SHM_SIZE_MB` | `128` |
| `GIGA_AGENT_LOCAL_DOCKER_MAX_ACTIVE_SANDBOXES` | `3` |
| `GIGA_AGENT_LOCAL_DOCKER_READONLY_ROOTFS` | `false` |
| `GIGA_AGENT_LOCAL_JUPYTER_STARTUP_TIMEOUT_SEC` | `20` |
| `GIGA_AGENT_LOCAL_JUPYTER_GRACEFUL_SHUTDOWN_TIMEOUT_SEC` | `5` |
| `GIGA_AGENT_LOCAL_JUPYTER_SECURE_EXEC_DEFAULT` | `false` |
| `GIGA_AGENT_LOCAL_JUPYTER_SECURE_EXEC_BACKEND` | `auto` |
| `GIGA_AGENT_LOCAL_JUPYTER_NETWORK_MODE` | `host` |

Подробнее см. [Изолированная среда и безопасность](./sandbox-security.md).

## Лимиты на пользователя

| Переменная | Значение по умолчанию | Назначение |
|---|---:|---|
| `GIGA_AGENT_MAX_ACTIVE_THREADS_PER_USER` | `5` | Максимум одновременно активных (выполняющихся) диалогов графа на пользователя. Значение `0` или меньше отключает лимит. |
| `GIGA_AGENT_LOCAL_JUPYTER_MAX_KERNELS_PER_USER` | `5` | Максимум одновременных локальных Jupyter-ядер на пользователя. При достижении лимита перед созданием нового ядра вытесняется наименее недавно использованное ядро того же пользователя. `0` отключает лимит. |

## OAuth-приложение Яндекса

Интеграции Яндекса ([Почта, Календарь, Диск](../user-guide/yandex-services.md)) подключаются пользователями по OAuth. Для этого администратор один раз регистрирует приложение на [oauth.yandex.ru](https://oauth.yandex.ru/) и задаёт его данные переменными окружения:

| Переменная | Назначение |
|---|---|
| `YANDEX_OAUTH_CLIENT_ID` | Идентификатор приложения; общий для Календаря и Диска. |
| `YANDEX_OAUTH_CLIENT_SECRET` | Секрет приложения. |
| `YANDEX_OAUTH_REDIRECT_URI` | Необязательный явный адрес обратного вызова; без него собирается из `GIGA_AGENT_BASE_URL` и префикса программного интерфейса. |
| `YANDEX_OAUTH_CLIENT_ID_YANDEX_MAIL` | Отдельное приложение для Почты: Яндекс требует под почтовую область доступа своё приложение. Без этой пары Почта использует общие данные выше. |
| `YANDEX_OAUTH_CLIENT_SECRET_YANDEX_MAIL` | Секрет почтового приложения. |

Пока переменные не заданы, кнопка подключения по OAuth в [каталоге коннекторов](../user-guide/connectors.md) неактивна, а карточки сервисов подсказывают, как включить приложение. Интеграции при этом работают на ручных токенах.

## Каналы

Боты каналов ([Telegram](../user-guide/channels.md)) создаются в **Настройки → Каналы**: тип канала и токен бота задаются в форме, храниться в переменных окружения им не нужно. Доступ контактам открывается вручную — до одобрения бот не отвечает.

## Адреса программного интерфейса

При `giga_agent dev` веб-интерфейс получает рабочую конфигурацию из `/app-config.js`. Обычно она указывает:

```json
{"basePath":"/","apiBasePath":"/api","apiAgentBasePath":"/api/agent"}
```

Поэтому для запросов из браузера или `curl` используйте `/api/agent/...`, хотя внутренние маршруты GigaAgent начинаются с `/agent/...`.

## Docker Compose

`docker-compose.yml` поднимает nginx, серверную часть, PostgreSQL, Redis, Qdrant и использует `.env`. Для простого локального запуска обычно достаточно `giga_agent dev`.

## Секретный ключ

Для общего сервера всегда задавайте `GIGA_AGENT_SECRET_KEY` явно и используйте длинное случайное значение. Не переиспользуйте демонстрационные значения и не публикуйте секреты в документации или журналах.
