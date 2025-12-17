build_graph:
	langgraph build -t giga_agent -c backend/graph/langgraph.json

init_files:
	cp -R backend/repl/files .

up:
	docker compose --env-file .docker.env up -d

down:
	docker compose --env-file .docker.env down

build:
	docker compose --env-file .docker.env build

up_dev:
	docker compose -p giga_agent_dev -f docker-compose.yml -f docker-compose.dev.yml --env-file .docker.env up -d

down_dev:
	docker compose -p giga_agent_dev -f docker-compose.yml -f docker-compose.dev.yml --env-file .docker.env down

build_dev:
	docker compose -p giga_agent_dev -f docker-compose.yml -f docker-compose.dev.yml --env-file .docker.env build
