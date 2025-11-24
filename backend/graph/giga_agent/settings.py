from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMSettings(BaseSettings):
    giga_agent_llm: str = Field(default="gigachat:GigaChat-2-Max")
    giga_agent_llm_fast: str = Field(default="gigachat:GigaChat-2-Pro")
    giga_agent_embeddings: str = Field(default="gigachat:EmbeddingsGigaR")
    giga_agent_sentiment_model: str = Field(default="models/sentiment_gigachat.joblib")
    giga_agent_lang: str = Field(default="ru-RU")

    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


class ProviderSettings(BaseSettings):
    # GigaChat
    gigachat_credentials: str
    gigachat_scope: Optional[str] = Field(default=None)
    gigachat_verify_ssl_certs: bool = Field(default=False)
    gigachat_timeout: float = Field(default=60.0)

    # Main GigaChat (Specific overrides)
    main_gigachat_credentials: Optional[str] = Field(default=None)
    main_gigachat_scope: Optional[str] = Field(default=None)
    main_gigachat_timeout: float = Field(default=15.0)
    main_gigachat_top_p: float = Field(default=0.5)

    # OpenAI - for image generation only
    openai_api_key: Optional[str] = Field(default=None)

    # LangSmith
    langsmith_api_key: Optional[str] = Field(default=None)

    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


class ImageGenSettings(BaseSettings):
    image_gen_name: Optional[str] = Field(default=None)
    image_gen_parallel: int = Field(default=5)

    # FusionBrain / Kandinsky
    kandinsky_api_key: Optional[str] = Field(default=None)
    kandinsky_secret_key: Optional[str] = Field(default=None)

    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


class ExternalServicesSettings(BaseSettings):
    tavily_api_key: Optional[str] = Field(default=None)
    vk_token: Optional[str] = Field(default=None)
    github_personal_access_token: Optional[str] = Field(default=None)
    owm_api_key: Optional[str] = Field(default=None)
    twogis_token: Optional[str] = Field(default=None)
    salute_speech: Optional[str] = Field(default=None)
    sber_tts_timeout: float = Field(default=30.0)

    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


class InternalSettings(BaseSettings):
    jupyter_client_api: str = Field(default="http://127.0.0.1:9090")
    jupyter_upload_api: str = Field(default="http://127.0.0.1:9092")
    tool_client_api: str = Field(default="http://127.0.0.1:8811")
    langgraph_api_url: str = Field(default="http://0.0.0.0:2024")
    files_dir: str = Field(default="files")
    jina_reader_url: str = Field(default="https://r.jina.ai/")
    character_limit: int = Field(default=100000)

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
        env_file=(".env", "../../.env"),  # Resolved from CWD (backend/graph/)
        env_file_encoding="utf-8",
        extra="ignore",  # Ignore extra fields in .env
        env_nested_delimiter="__",  # Allows overriding nested fields via env vars if needed, though aliases handle most
    )


# Global settings instance
settings = Settings()
