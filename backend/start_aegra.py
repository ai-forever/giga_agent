from __future__ import annotations

import argparse
import os
import sys
from typing import Final


DEFAULT_APP: Final[str] = "aegra_api.main:app"
DEFAULT_HOST: Final[str] = "127.0.0.1"
DEFAULT_PORT: Final[int] = 8000

# docker-compose.yml publishes langgraph-postgres on host 5433
DEFAULT_POSTGRES_URL: Final[str] = (
    "postgres://postgres:postgres@localhost:5433/postgres?sslmode=disable"
)
os.environ["DATABASE_URL"] = (
    "postgresql+asyncpg://postgres:postgres@localhost:5433/postgres"
)
os.environ["GIGA_AGENT_UI"] = "0"
os.environ["REDIS_URL"] = "redis://localhost:6379"
os.environ["AEGRA_CONFIG"] = "langgraph.json"
os.environ["AUTH_TYPE"] = "custom"
os.environ["GIGA_AGENT_SECRET_KEY"] = "secret"
os.environ["GIGA_AGENT_DATABASE_URL"] = (
    "postgresql+asyncpg://postgres:postgres@localhost:5434/postgres"
)
os.environ["QDRANT_URL"] = "http://localhost:6333"
os.environ["GIGA_AGENT_LANGGRAPH_API_URL"] = "http://127.0.0.1:8000"


def main(argv: list[str] | None = None) -> int:
    try:
        import uvicorn
    except Exception as e:  # pragma: no cover
        print(f"Failed to import uvicorn: {e}", file=sys.stderr)
        return 1

    try:
        uvicorn.run(
            DEFAULT_APP,
            host=DEFAULT_HOST,
            port=DEFAULT_PORT,
            reload=True,
            log_level="info",
        )
    except Exception as e:  # pragma: no cover
        print(f"Failed to start Aegra API: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
