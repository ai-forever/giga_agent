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

    # Main GigaChat (needed for upload server GigaChat instance)
    main_gigachat_user: Optional[str] = Field(default=None)
    main_gigachat_password: Optional[str] = Field(default=None)
    main_gigachat_credentials: Optional[str] = Field(default=None)
    main_gigachat_scope: Optional[str] = Field(default=None)
    main_gigachat_base_url: Optional[str] = Field(default=None)
    repl_gigachat_timeout: float = Field(default=100000.0)
    main_gigachat_top_p: float = Field(default=0.5)
    main_gigachat_verbose: Optional[str] = Field(default=None)
    main_gigachat_verify_ssl_certs: bool = Field(default=False)
    main_gigachat_max_tokens: int = Field(default=32000)

    def model_post_init(self, __context) -> None:
        """Validate GigaChat authentication configuration."""
        has_credentials = bool(self.main_gigachat_credentials)
        has_user_pass = bool(self.main_gigachat_user and self.main_gigachat_password)

        if not (has_credentials or has_user_pass):
            raise ValueError(
                "Main GigaChat authentication not configured. Provide either:\n"
                "  - MAIN_GIGACHAT_CREDENTIALS (OAuth token), OR\n"
                "  - MAIN_GIGACHAT_USER + MAIN_GIGACHAT_PASSWORD (basic auth)"
            )

    model_config = SettingsConfigDict(
        env_file=(
            ".env",
            "../../.env",
        ),  # Resolved from backend/repl/app/ -> ../../.env (project root)
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = ReplSettings()
