import asyncio
import json
import re
from typing import Any

import aiohttp
from langchain_core.messages import HumanMessage, SystemMessage

from giga_agent.agents.podcast.config import podcast_llm
from giga_agent.agents.podcast.constants import (
    JINA_READER_URL,
    JINA_RETRY_ATTEMPTS,
    JINA_RETRY_DELAY,
)
from giga_agent.agents.podcast.schema import MediumDialogue, ShortDialogue


async def parse_url(url: str) -> str:
    """Асинхронный парсинг URL и возврат текстового содержимого."""
    full_url = f"{JINA_READER_URL}{url}"
    for attempt in range(1, JINA_RETRY_ATTEMPTS + 1):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(full_url, timeout=60) as response:
                    response.raise_for_status()
                    return await response.text()
        except (TimeoutError, aiohttp.ClientError) as e:
            if attempt == JINA_RETRY_ATTEMPTS:
                raise ValueError(
                    f"Failed to fetch URL after {JINA_RETRY_ATTEMPTS} attempts: {e}",
                ) from e
            # Ожидаем перед следующей попыткой
            await asyncio.sleep(JINA_RETRY_DELAY)


async def generate_script(
    system_prompt: str,
    input_text: str,
    output_model: type[ShortDialogue] | type[MediumDialogue],
) -> ShortDialogue | MediumDialogue:
    """Получение диалога от LLM."""
    # Вызов LLM в первый раз
    first_draft_dialogue = await call_gigachat(system_prompt, input_text, output_model)

    if first_draft_dialogue is None:
        raise Exception("Failed to get the first dialogue draft from GigaChat")

    # Вызов LLM во второй раз для улучшения диалога
    system_prompt_with_dialogue = (
        f"{system_prompt}\n\n Вот первый черновик диалога, "
        f"который ты предоставил:\n\n{first_draft_dialogue.model_dump_json()}."
    )
    final_dialogue = await call_gigachat(
        system_prompt_with_dialogue,
        "Пожалуйста, улучши диалог. Сделай его более естественным и увлекательным.",
        output_model,
    )

    if final_dialogue is None:
        return first_draft_dialogue

    return final_dialogue


def parse_text_to_json(text: str, dialogue_format: Any) -> Any | None:
    """Преобразование текстового диалога в JSON формат."""
    try:
        # Пытаемся найти JSON в тексте
        json_match = re.search(r"\{.*\}", text, re.DOTALL)
        if json_match:
            try:
                response_json = json.loads(json_match.group())
                if dialogue_format == ShortDialogue:
                    return ShortDialogue(**response_json)
                if dialogue_format == MediumDialogue:
                    return MediumDialogue(**response_json)
            except Exception:
                pass

        # Если JSON не найден, парсим текстовый диалог
        lines = text.strip().split("\n")
        dialogue = []
        current_speaker = None
        current_text = ""

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Определяем спикера
            if line.startswith("Ведущая:") or line.startswith("Жанна:"):
                if current_speaker and current_text:
                    dialogue.append(
                        {"speaker": current_speaker, "text": current_text.strip()},
                    )
                current_speaker = "Ведущая (Жанна)"
                current_text = line.split(":", 1)[1].strip() if ":" in line else ""
            elif line.startswith("Гость:"):
                if current_speaker and current_text:
                    dialogue.append(
                        {"speaker": current_speaker, "text": current_text.strip()},
                    )
                current_speaker = "Гость"
                current_text = line.split(":", 1)[1].strip() if ":" in line else ""
            # Продолжение текста
            elif current_text:
                current_text += " " + line
            else:
                current_text = line

        # Добавляем последнюю реплику
        if current_speaker and current_text:
            dialogue.append({"speaker": current_speaker, "text": current_text.strip()})

        # Создаем JSON объект
        result_json = {
            "scratchpad": "Диалог извлечен из текстового ответа GigaChat",
            "name_of_guest": "Эксперт",
            "dialogue": dialogue,
        }

        if dialogue_format == ShortDialogue:
            return ShortDialogue(**result_json)
        if dialogue_format == MediumDialogue:
            return MediumDialogue(**result_json)

    except Exception:
        return None


async def call_gigachat(
    system_prompt: str,
    text: str,
    dialogue_format: Any,
) -> Any | None:
    """Вызов GigaChat API с заданным промптом и форматом диалога."""
    try:
        messages = [SystemMessage(content=system_prompt), HumanMessage(content=text)]

        response = await podcast_llm.ainvoke(messages)
        response_text = response.content

        # Парсим JSON ответ
        try:
            response_json = json.loads(response_text)

            # Создаем объект нужного типа
            if dialogue_format == ShortDialogue:
                return ShortDialogue(**response_json)
            if dialogue_format == MediumDialogue:
                return MediumDialogue(**response_json)
            return None

        except json.JSONDecodeError:
            # Пытаемся преобразовать текстовый ответ в JSON
            parsed_result = parse_text_to_json(response_text, dialogue_format)
            if parsed_result:
                return parsed_result
            return None
        except Exception:
            return None

    except Exception:
        return None
