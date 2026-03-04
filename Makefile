up:
	docker compose -d

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
