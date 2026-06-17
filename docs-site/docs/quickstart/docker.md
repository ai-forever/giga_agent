---
title: "Быстрый старт через Docker"
description: "Как поднять GigaAgent через Docker Compose."
---

# Быстрый старт через Docker

`docker-compose.yml` поднимает набор служб: nginx, серверную часть GigaAgent, PostgreSQL, Redis, Qdrant, тома данных и сеть. Nginx публикуется на `8123:80`.

Для простого локального знакомства с пакетом обычно быстрее использовать [локальный запуск](./local.md). Docker Compose полезен, когда нужно проверить инфраструктурный сценарий с отдельными службами.

## Минимальная подготовка

Создайте `.env` на основе примера и задайте секретный ключ:

```bash
cp .env.example .env
# отредактируйте .env
```

Минимально важные переменные:

```env
GIGA_AGENT_SECRET_KEY=<long-random-secret>
GIGA_AGENT_HOST_PROJECT_PATH=<absolute-host-path-if-local-docker-sandbox-is-used>
```

`.env.example` не является полной справкой по настройкам. Основные переменные описаны в разделе [Конфигурация](../operations/configuration.md).

## Запуск

```bash
docker compose up --build
```

После старта откройте:

```text
http://localhost:8123
```

## Что поднимается

Проверенные настройки службы GigaAgent в `docker-compose.yml`:

- база приложения: `GIGA_AGENT_DATABASE_URL=postgresql+asyncpg://...`;
- Qdrant: `QDRANT_URL=http://qdrant:6333`;
- адрес LangGraph API внутри сети: `GIGA_AGENT_LANGGRAPH_API_URL=http://giga-agent:8000`;
- рабочий каталог: `GIGA_AGENT_PROJECT_ROOT=/.giga_agent`;
- Docker-доступ берётся из окружения или `unix:///var/run/docker.sock`;
- команда запуска: `/app/deployments/aegra-startup.sh`.

`docker-compose.dev.yml` содержит настройки для разработки. Не копируйте абсолютные пути из него без замены на свои.

## После запуска

1. Войдите через веб-интерфейс.
2. Настройте коннектор и языковую модель.
3. Для RAG настройте векторные представления и проверьте Qdrant.
4. Для выполнения кода настройте изолированную среду и проверьте границы доступа к файловой системе.
