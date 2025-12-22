import asyncio
from typing import Literal

from gigachat.exceptions import ResponseError
from langchain.chat_models import init_chat_model
from langchain.embeddings import init_embeddings
from langchain_gigachat import GigaChat, GigaChatEmbeddings

from giga_agent.settings import settings
from giga_agent.utils.types import FileTypes

GIGACHAT_PROVIDER = "gigachat:"


def _get_llm_model(tag: str = None) -> str:
    if tag == "fast":
        return settings.llm.giga_agent_llm_fast
    return settings.llm.giga_agent_llm


def load_gigachat(tag: str = None, is_main: bool = False):
    llm_str = _get_llm_model(tag)
    has_creds = bool(settings.providers.gigachat_credentials)
    has_up = bool(
        settings.providers.gigachat_user and settings.providers.gigachat_password
    )

    if not (has_creds or has_up):
        raise ValueError(
            "GigaChat authentication not configured. Provide either:\n"
            "  - GIGACHAT_CREDENTIALS (OAuth token), OR\n"
            "  - GIGACHAT_USER + GIGACHAT_PASSWORD (basic auth)",
        )

    # Настройки по умолчанию
    kwargs = dict(
        timeout=settings.providers.gigachat_timeout,
        user=settings.providers.gigachat_user,
        password=settings.providers.gigachat_password,
        credentials=settings.providers.gigachat_credentials,
        scope=settings.providers.gigachat_scope,
        verify_ssl_certs=settings.providers.gigachat_verify_ssl_certs,
    )

    if is_main:
        # Check that at least one auth method is provided for main GigaChat
        has_main_creds = bool(settings.providers.main_gigachat_credentials)
        has_main_up = bool(
            settings.providers.main_gigachat_user
            and settings.providers.main_gigachat_password
        )

        if not (has_main_creds or has_main_up):
            raise ValueError(
                "Main GigaChat authentication not configured. Provide either:\n"
                "  - MAIN_GIGACHAT_CREDENTIALS (OAuth token), OR\n"
                "  - MAIN_GIGACHAT_USER + MAIN_GIGACHAT_PASSWORD (basic auth)",
            )
        kwargs = dict(
            timeout=settings.providers.main_gigachat_timeout,
            user=settings.providers.main_gigachat_user,
            password=settings.providers.main_gigachat_password,
            credentials=settings.providers.main_gigachat_credentials,
            scope=settings.providers.main_gigachat_scope,
            base_url=settings.providers.main_gigachat_base_url,
            top_p=settings.providers.main_gigachat_top_p,
            verbose=settings.providers.main_gigachat_verbose,
        )
    return GigaChat(
        model=llm_str[len(GIGACHAT_PROVIDER) :],
        profanity_check=False,
        max_tokens=1280000,
        **kwargs,
    )


def load_gigachat_embeddings():
    llm_str = settings.llm.giga_agent_embeddings
    return GigaChatEmbeddings(
        model=llm_str[len(GIGACHAT_PROVIDER) :],
        user=settings.providers.gigachat_user,
        password=settings.providers.gigachat_password,
        credentials=settings.providers.gigachat_credentials,
        scope=settings.providers.gigachat_scope,
        verify_ssl_certs=settings.providers.gigachat_verify_ssl_certs,
    )


def is_llm_gigachat(tag: str = None):
    llm_str = _get_llm_model(tag)
    return llm_str.startswith(GIGACHAT_PROVIDER)


# Singletons cache
_LLM_SINGLETONS: dict[str, object] = {}
_EMBEDDINGS_SINGLETON: object | None = None


def load_llm(tag: str = None, is_main: bool = False):
    env_key = "GIGA_AGENT_LLM_FAST" if tag == "fast" else "GIGA_AGENT_LLM"
    # TODO: Поправить логику загрузки LLM кредов (сейчас это вообще что-то страшное)
    singleton_key = env_key
    if is_main:
        singleton_key = "MAIN_" + singleton_key

    if singleton_key in _LLM_SINGLETONS:
        return _LLM_SINGLETONS[singleton_key]

    llm_str = _get_llm_model(tag)

    if llm_str.startswith(GIGACHAT_PROVIDER):
        llm = load_gigachat(tag=tag, is_main=is_main)
    else:
        llm = init_chat_model(llm_str)

    _LLM_SINGLETONS[singleton_key] = llm
    return llm


def load_embeddings():
    global _EMBEDDINGS_SINGLETON

    if _EMBEDDINGS_SINGLETON is not None:
        return _EMBEDDINGS_SINGLETON

    emb_str = settings.llm.giga_agent_embeddings

    if emb_str.startswith(GIGACHAT_PROVIDER):
        embeddings = load_gigachat_embeddings()
    else:
        embeddings = init_embeddings(emb_str)

    _EMBEDDINGS_SINGLETON = embeddings
    return embeddings


def is_llm_image_inline():
    llm_str = settings.llm.giga_agent_llm
    return llm_str.startswith(GIGACHAT_PROVIDER)


async def upload_file_with_retry(
    file: FileTypes,
    purpose: Literal["general", "assistant"] = "general",
    retries=3,
):
    llm = load_llm()
    retry = 0
    while retry < retries:
        try:
            file = await llm.aupload_file(file, purpose)
            return file.id_
        except ResponseError as e:
            if e.args[1] != 504:
                raise e
            retry += 1
            await asyncio.sleep(0.5)
