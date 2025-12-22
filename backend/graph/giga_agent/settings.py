from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMSettings(BaseSettings):
    giga_agent_llm: str = Field(default="gigachat:GigaChat-2-Max")
    giga_agent_llm_fast: str = Field(default="gigachat:GigaChat-2-Pro")
    giga_agent_embeddings: str = Field(default="gigachat:EmbeddingsGigaR")
    giga_agent_sentiment_model: str = Field(default="models/sentiment_gigachat.joblib")
    giga_agent_lang: str = Field(default="ru-RU")
    giga_agent_mcp_config: dict = Field(default={})
    giga_agent_user_notes: str = Field(default="")
    giga_agent_memory_enabled: bool = Field(default=True)

    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


class ProviderSettings(BaseSettings):
    # GigaChat
    gigachat_credentials: str | None = Field(default=None)
    gigachat_user: str | None = Field(default=None)
    gigachat_password: str | None = Field(default=None)
    gigachat_scope: str = Field(default="GIGACHAT_API_PERS")
    gigachat_verify_ssl_certs: bool = Field(default=False)
    gigachat_timeout: float = Field(default=60.0)

    # Main GigaChat
    main_gigachat_user: str | None = Field(default=None)
    main_gigachat_password: str | None = Field(default=None)
    main_gigachat_credentials: str | None = Field(default=None)
    main_gigachat_scope: str = Field(default="GIGACHAT_API_PERS")
    main_gigachat_base_url: str | None = Field(default=None)
    main_gigachat_timeout: float = Field(default=15.0)
    main_gigachat_top_p: float = Field(default=0.5)
    main_gigachat_verbose: str | None = Field(default=None)

    # OpenAI - for image generation only
    openai_api_key: str | None = Field(default=None)

    # LangSmith
    langsmith_api_key: str | None = Field(default=None)

    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


class ImageGenSettings(BaseSettings):
    image_gen_name: str | None = Field(default=None)
    image_gen_parallel: int = Field(default=5)

    # FusionBrain / Kandinsky
    kandinsky_api_key: str | None = Field(default=None)
    kandinsky_secret_key: str | None = Field(default=None)

    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


class ExternalServicesSettings(BaseSettings):
    tavily_api_key: str | None = Field(default=None)
    vk_token: str | None = Field(default=None)
    github_personal_access_token: str | None = Field(default=None)
    owm_api_key: str | None = Field(default=None)
    twogis_token: str | None = Field(default=None)
    salute_speech: str | None = Field(default=None)
    salute_speech_scope: str = Field(default="SALUTE_SPEECH_PERS")
    sber_tts_timeout: float = Field(default=30.0)

    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


class InternalSettings(BaseSettings):
    jupyter_client_api: str = Field(default="http://repl:9090")
    jupyter_upload_api: str = Field(default="http://upload_server:9092")
    tool_client_api: str = Field(default="http://tool_server:9091")
    langgraph_api_url: str = Field(default="http://langgraph-api:8000/")
    files_dir: str = Field(default="files")
    jina_reader_url: str = Field(default="https://r.jina.ai/")
    character_limit: int = Field(default=100000)
    langconnect_api_url: str | None = Field(default=None)
    langconnect_api_secret_token: str | None = Field(default=None)
    front_base_url: str = Field(default="http://frontend:80/files")
    postgres_db: str = Field(default="postgres")
    postgres_host: str = Field(default="aegra-postgres")
    postgres_port: int = Field(default=5432)
    postgres_user: str = Field(default="postgres")
    postgres_password: str = Field(default="postgres")

    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


class FeatureSettings(BaseSettings):
    repl_from_message: bool = Field(default=True)
    plotly_renderer: str = Field(default="plotly_mimetype")

    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


class Settings(BaseSettings):
    llm: LLMSettings = Field(default_factory=LLMSettings)
    providers: ProviderSettings = Field(default_factory=ProviderSettings)
    image_gen: ImageGenSettings = Field(default_factory=ImageGenSettings)
    external: ExternalServicesSettings = Field(default_factory=ExternalServicesSettings)
    internal: InternalSettings = Field(default_factory=InternalSettings)
    features: FeatureSettings = Field(default_factory=FeatureSettings)

    model_config = SettingsConfigDict(
        # Resolved from CWD (backend/graph/)
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        # Ignore extra fields in .env
        extra="ignore",
        # Allows overriding nested fields via env vars if needed,
        # though aliases handle most
        env_nested_delimiter="__",
    )


# Global settings instance
settings = Settings()
