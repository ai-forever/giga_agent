from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ReplSettings(BaseSettings):
    state_dir: str = Field(default="kernel_states", alias="STATE_DIR")
    max_kernel_live: float = Field(default=300.0, alias="MAX_KERNEL_LIVE")
    upload_dir: str = Field(default="uploads", alias="UPLOAD_DIR")
    plotly_renderer: str = Field(default="plotly_mimetype", alias="PLOTLY_RENDERER")

    # LangGraph API URL (needed for upload server)
    langgraph_api_url: str = Field(default="", alias="LANGGRAPH_API_URL")

    # Files directory (needed for upload server)
    files_dir: str = Field(default="files", alias="FILES_DIR")

    # Main GigaChat (needed for upload server GigaChat instance)
    main_gigachat_user: str = Field(default="", alias="MAIN_GIGACHAT_USER")
    main_gigachat_password: str = Field(default="", alias="MAIN_GIGACHAT_PASSWORD")
    main_gigachat_credentials: str = Field(
        default="", alias="MAIN_GIGACHAT_CREDENTIALS"
    )
    main_gigachat_scope: str = Field(default="", alias="MAIN_GIGACHAT_SCOPE")
    main_gigachat_base_url: str = Field(default="", alias="MAIN_GIGACHAT_BASE_URL")

    model_config = SettingsConfigDict(
        env_file=(
            ".env",
            "../../.env",
        ),  # Resolved from backend/repl/app/ -> ../../.env (project root)
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = ReplSettings()
