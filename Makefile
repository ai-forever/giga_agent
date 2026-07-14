up:
	docker compose up -d

down:
	docker compose down

build:
	docker compose build

up_dev:
	docker compose -p giga_agent_dev -f docker-compose.dev.yml up -d

down_dev:
	docker compose -p giga_agent_dev -f docker-compose.dev.yml down

build_dev:
	docker compose -p giga_agent_dev -f docker-compose.dev.yml build

# --- Observability (Prometheus/Grafana/Loki), separate stack joining the main
# network as external. Bring the main stack up first. See deployments/observability/README.md
OBS_COMPOSE = docker compose -p observability -f deployments/observability/docker-compose.yml

observability_up:
	$(OBS_COMPOSE) up -d

observability_down:
	$(OBS_COMPOSE) down

observability_up_dev:
	GIGA_AGENT_DOCKER_NETWORK=giga-agent-net-dev GRAFANA_PORT=3001 $(OBS_COMPOSE) up -d

observability_down_dev:
	GIGA_AGENT_DOCKER_NETWORK=giga-agent-net-dev $(OBS_COMPOSE) down
