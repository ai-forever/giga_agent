"""Speech-to-text route backed by Sber SaluteSpeech /speech:recognize."""

from __future__ import annotations

import io
import os
import uuid
from typing import Annotated

import aiohttp
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from pydub import AudioSegment

from giga_agent.conf import GIGA_AGENT_STT_ENABLED, GIGA_AGENT_STT_RUNTIME
from giga_agent.models.users import User
from giga_agent.modules.auth.api import get_current_active_user

router = APIRouter(prefix="/stt", tags=["stt"])

SALUTE_SPEECH_OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
SALUTE_SPEECH_RECOGNIZE_URL = "https://smartspeech.sber.ru/rest/v1/speech:recognize"

# SaluteSpeech accepts audio/x-pcm;bit=16;rate=16000 natively. Browsers record
# WebM/Opus, so we transcode to 16 kHz mono PCM16 on the way through.
PCM_SAMPLE_RATE = 16000
PCM_CHANNELS = 1
PCM_SAMPLE_WIDTH = 2  # 16-bit


class RecognizeResponse(BaseModel):
    text: str


def _transcode_to_pcm16(data: bytes) -> bytes:
    audio = AudioSegment.from_file(io.BytesIO(data))
    audio = (
        audio.set_frame_rate(PCM_SAMPLE_RATE)
        .set_channels(PCM_CHANNELS)
        .set_sample_width(PCM_SAMPLE_WIDTH)
    )
    return audio.raw_data


async def _fetch_salute_token(auth_token: str, scope: str) -> str:
    """Fetch an access token; raises HTTPException with a distinguishable cause."""
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "RqUID": str(uuid.uuid4()),
        "Authorization": f"Basic {auth_token}",
    }
    try:
        async with (
            aiohttp.ClientSession() as session,
            session.post(
                SALUTE_SPEECH_OAUTH_URL,
                headers=headers,
                data={"scope": scope},
                ssl=False,
                timeout=30,
            ) as response,
        ):
            body_text = await response.text()
            if response.status == 401 or response.status == 403:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=(
                        f"SaluteSpeech rejected credentials (HTTP {response.status}). "
                        f"Check SALUTE_SPEECH / SALUTE_SCOPE. Body: {body_text[:200]}"
                    ),
                )
            if response.status >= 400:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=(
                        f"SaluteSpeech OAuth error (HTTP {response.status}): "
                        f"{body_text[:200]}"
                    ),
                )
            try:
                body = await response.json(content_type=None)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"SaluteSpeech OAuth returned non-JSON: {body_text[:200]}",
                ) from exc
            token = body.get("access_token") if isinstance(body, dict) else None
            if not token:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="SaluteSpeech OAuth response lacked access_token",
                )
            return token
    except TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="SaluteSpeech OAuth request timed out",
        ) from exc
    except aiohttp.ClientError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"SaluteSpeech OAuth transport error: {exc}",
        ) from exc


@router.post("/recognize", response_model=RecognizeResponse)
async def recognize_speech(
    current_user: Annotated[User, Depends(get_current_active_user)],
    audio: UploadFile = File(...),
) -> RecognizeResponse:
    if not GIGA_AGENT_STT_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="STT is disabled (set GIGA_AGENT_STT_ENABLED=1)",
        )
    if (GIGA_AGENT_STT_RUNTIME or "").strip().lower() != "salute":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Unsupported STT runtime '{GIGA_AGENT_STT_RUNTIME}'",
        )
    auth_token = os.environ.get("SALUTE_SPEECH")
    if not auth_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SALUTE_SPEECH credential is not configured",
        )

    raw = await audio.read()
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Empty audio payload",
        )

    try:
        pcm = _transcode_to_pcm16(raw)
    except Exception as exc:  # pydub wraps ffmpeg, swallow its specifics
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported audio payload: {exc}",
        ) from exc

    scope = os.environ.get("SALUTE_SCOPE", "SALUTE_SPEECH_PERS")
    token = await _fetch_salute_token(auth_token=auth_token, scope=scope)

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": f"audio/x-pcm;bit=16;rate={PCM_SAMPLE_RATE}",
    }
    params = {"language": "ru-RU"}

    try:
        async with (
            aiohttp.ClientSession() as session,
            session.post(
                SALUTE_SPEECH_RECOGNIZE_URL,
                headers=headers,
                params=params,
                data=pcm,
                ssl=False,
                timeout=60,
            ) as response,
        ):
            if response.status >= 400:
                body = await response.text()
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"SaluteSpeech error {response.status}: {body}",
                )
            body = await response.json()
    except aiohttp.ClientError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"SaluteSpeech transport error: {exc}",
        ) from exc
    except TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="SaluteSpeech request timed out",
        ) from exc

    # SaluteSpeech returns {"status": 200, "result": ["transcribed text", ...]}
    parts = body.get("result") if isinstance(body, dict) else None
    if not isinstance(parts, list):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unexpected SaluteSpeech response shape",
        )
    text = " ".join(p for p in parts if isinstance(p, str)).strip()
    return RecognizeResponse(text=text)
