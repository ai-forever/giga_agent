from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ReplSettings(BaseSettings):
    # REPL-specific settings
    state_dir: str = Field(default="kernel_states")
    max_kernel_live: float = Field(default=300.0)
    upload_dir: str = Field(default="uploads")
    plotly_renderer: str = Field(default="plotly_mimetype")

    # LangGraph API URL (needed for upload server)
    langgraph_api_url: Optional[str] = Field(default=None)

    # Files directory (needed for upload server)
    files_dir: str = Field(default="files")
    runs_dir: str = Field(default="runs")

    giga_agent_api: str = Field(default="")
    tool_client_api: str = Field(default="http://127.0.0.1:8811")

    model_config = SettingsConfigDict(
        env_file=(
            ".env",
            "../../.env",
        ),  # Resolved from backend/repl/app/ -> ../../.env (project root)
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = ReplSettings()
