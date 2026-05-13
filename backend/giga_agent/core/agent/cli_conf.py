"""CLI runtime configuration loaded from giga_agent.conf.json.

When GIGA_AGENT_RUNTIME=cli, the system loads runtime config from a JSON
file instead of querying the database.  Lookup order:
  1. GIGA_AGENT_CLI_CONFIG env var (JSON string)
  2. CWD / giga_agent.conf.json
  3. giga_agent_dir() / giga_agent.conf.json
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from giga_agent.conf import get_settings

CONF_FILENAME = "giga_agent.conf.json"


class CliConnectorConf(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    type: str = Field(alias="__type")

    @property
    def settings(self) -> dict[str, Any]:
        return self.model_extra or {}


class CliLLMConf(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    connector: CliConnectorConf
    type: str = Field(alias="__type")
    model_id: str

    @property
    def settings(self) -> dict[str, Any]:
        return self.model_extra or {}


class CliEmbeddingConf(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    connector: CliConnectorConf
    type: str = Field(alias="__type")
    model_id: str
    vector_size: int = 1536

    @property
    def settings(self) -> dict[str, Any]:
        return self.model_extra or {}


class CliSearchEngineConf(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    connector: CliConnectorConf
    type: str = Field(alias="__type")

    @property
    def settings(self) -> dict[str, Any]:
        return self.model_extra or {}


class CliImageGeneratorConf(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    connector: CliConnectorConf
    type: str = Field(alias="__type")

    @property
    def settings(self) -> dict[str, Any]:
        return self.model_extra or {}


class CliRuntimeConf(BaseModel):
    llm: CliLLMConf
    fast_llm: CliLLMConf | None = None
    embedding: CliEmbeddingConf | None = None
    sandbox: str = "local_jupyter"
    search_engine: CliSearchEngineConf | None = None
    image_generator: CliImageGeneratorConf | None = None
    user_settings: dict[str, Any] = Field(default_factory=dict)


def _find_conf_path() -> Path:
    """Locate giga_agent.conf.json (CWD first, then giga_agent_dir)."""
    cwd_path = Path.cwd() / CONF_FILENAME
    if cwd_path.is_file():
        return cwd_path

    from giga_agent.core.paths import giga_agent_dir

    project_path = giga_agent_dir() / CONF_FILENAME
    if project_path.is_file():
        return project_path

    raise FileNotFoundError(
        f"CLI runtime config not found. Place {CONF_FILENAME} in the "
        f"current directory or in the giga_agent project root "
        f"({giga_agent_dir()})."
    )


@lru_cache(maxsize=1)
def load_cli_conf() -> CliRuntimeConf:
    """Load and parse the CLI runtime configuration (cached)."""
    raw_config = (get_settings().giga_agent_cli_config or "").strip()
    if raw_config:
        data = json.loads(raw_config)
    else:
        path = _find_conf_path()
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    return CliRuntimeConf.model_validate(data)


def reset_cli_conf_cache() -> None:
    """Clear the cached CLI conf (useful for testing)."""
    load_cli_conf.cache_clear()
