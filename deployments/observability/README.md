# Observability stack (Prometheus + Grafana + Loki)

Separate compose, decoupled from the main app (see `docs/observability-plan.md` §4).
Metrics via Prometheus, logs via Loki/Promtail, dashboards via Grafana.

## Запуск

Основной стек создаёт docker-сеть, поэтому поднимаем его **первым**, затем стек
мониторинга, подключающийся к той же сети как `external`:

```bash
# 1. основной стек (создаёт сеть giga-agent-net)
docker compose up -d

# 2. observability
docker compose -f deployments/observability/docker-compose.yml up -d
```

Grafana: http://localhost:3000 (admin / admin — переопределяется
`GRAFANA_ADMIN_PASSWORD`). Datasources (Prometheus, Loki) и дашборд
«GigaAgent — Infra / OOM» подхватываются автоматически (provisioning).

### Dev-стек

У dev-компоуза сеть называется иначе — задайте переменную:

```bash
GIGA_AGENT_DOCKER_NETWORK=giga-agent-net-dev \
  docker compose -f deployments/observability/docker-compose.yml up -d
```

Если сеть ещё не создана: `docker network create giga-agent-net`.

## Что скрейпится

`giga-agent` (app), `cadvisor`, `node-exporter`, `redis-exporter`,
два `postgres-exporter` (aegra + app), `qdrant` (нативный `/metrics`).

> **Target `giga-agent` будет DOWN**, пока не сделан этап 3
> (`GIGA_AGENT_METRICS_ENABLED=1` + подтверждённый путь `/metrics` за
> aegra-mount). Инфра-метрики (cadvisor/redis/pg/qdrant) работают сразу.

## Оговорки

- **macOS:** `cadvisor`/`node-exporter` рассчитаны на Linux-cgroups; на Docker
  Desktop метрики частичны. Полное покрытие — на Linux prod-хосте.
- **Loki-метки** держим низкокардинальными (`container`, `level`, `stream`).
  `run_id`/`thread_id`/`user_id` лежат внутри JSON-строки — фильтр через
  `{container="giga-agent"} | json | run_id="..."`.

## Готовые community-дашборды (импорт вручную)

Grafana → Dashboards → Import по ID (datasource = Prometheus):

- **1860** — Node Exporter Full
- **14282** — cAdvisor
- **763** — Redis
- **9628** — PostgreSQL (postgres_exporter)
