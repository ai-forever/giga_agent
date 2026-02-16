import asyncio
import uuid

import aiohttp

# Константы для Sber TTS
SBER_TTS_RETRY_ATTEMPTS = 3
SBER_TTS_RETRY_DELAY = 5  # в секундах

# Доступные голоса Sber SmartSpeech
SBER_VOICES = {
    "host": ["May_24000", "Ost_24000"],  # Женские голоса для ведущей
    "guest": ["Bys_24000", "Pon_24000"],  # Мужские голоса для гостя
}


async def get_sber_tts_token(
    auth_token: str,
    scope: str = "SALUTE_SPEECH_PERS",
) -> str | None:
    """Асинхронное получение токена доступа для Sber SmartSpeech API."""
    if not auth_token:
        return None

    rq_uid = str(uuid.uuid4())
    url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "RqUID": rq_uid,
        "Authorization": f"Basic {auth_token}",
    }
    data = {"scope": scope}

    for attempt in range(1, SBER_TTS_RETRY_ATTEMPTS + 1):
        try:
            async with (
                aiohttp.ClientSession() as session,
                session.post(
                    url,
                    headers=headers,
                    data=data,
                    ssl=False,
                    timeout=60,
                ) as response,
            ):
                response.raise_for_status()
                body = await response.json()
                token = body.get("access_token")
                if not token:
                    return None
                return token
        except (TimeoutError, aiohttp.ClientError):
            if attempt == SBER_TTS_RETRY_ATTEMPTS:
                return None
            await asyncio.sleep(SBER_TTS_RETRY_DELAY)

    return None


async def synthesize_sber_speech(
    text: str,
    token: str,
    format: str = "wav16",
    voice: str = "Bys_24000",
) -> bytes | None:
    """Асинхронный синтез речи через Sber SmartSpeech API."""
    url = "https://smartspeech.sber.ru/rest/v1/text:synthesize"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/text",
    }
    params = {"format": format, "voice": voice}

    for attempt in range(1, SBER_TTS_RETRY_ATTEMPTS + 1):
        try:
            async with (
                aiohttp.ClientSession() as session,
                session.post(
                    url,
                    headers=headers,
                    params=params,
                    data=text.encode("utf-8"),
                    ssl=False,
                    timeout=60,
                ) as response,
            ):
                response.raise_for_status()
                audio_bytes = await response.read()
                return audio_bytes
        except (TimeoutError, aiohttp.ClientError):
            if attempt == SBER_TTS_RETRY_ATTEMPTS:
                return None
            await asyncio.sleep(SBER_TTS_RETRY_DELAY)

    return None


async def generate_sber_audio(
    text: str,
    token: str,
    speaker: str,
    language: str = "ru",
) -> bytes | None:
    """Генерация аудио для подкаста с использованием Sber TTS.

    Args:
        text: Текст для синтеза
        speaker: Спикер ("Host (Jane)" или "Guest")
        language: Язык (не используется в Sber TTS, но сохранен для совместимости)

    Returns:
        Сырые байты аудио или None при ошибке

    """
    voice = "May_24000" if speaker == "Host (Jane)" else "Bys_24000"
    return await synthesize_sber_speech(text, token, voice=voice)


def get_available_voices() -> dict:
    """Возвращает доступные голоса."""
    return SBER_VOICES


async def generate_podcast_audio(
    text: str,
    token: str,
    speaker: str,
    language: str = "ru",
    use_sber_tts: bool = True,
) -> bytes | None:
    """Генерация аудио для подкаста используя Sber TTS."""
    if not use_sber_tts:
        raise Exception("Only Sber TTS is supported in this version")

    try:
        # Преобразуем имена спикеров для совместимости с Sber TTS
        if speaker == "Ведущая (Жанна)":
            speaker_name = "Host (Jane)"
        elif speaker == "Гость":
            speaker_name = "Guest"
        else:
            speaker_name = speaker

        return await generate_sber_audio(text, token, speaker_name, language)

    except Exception:
        raise
