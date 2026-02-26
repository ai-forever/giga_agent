import asyncio
import uuid
import warnings

from langchain.tools import ToolRuntime
from langchain_core.tools import tool
from langgraph.config import RunnableConfig
from langgraph.constants import START
from langgraph.graph import StateGraph
from langgraph.graph.ui import push_ui_message
from langgraph_sdk import get_client

warnings.filterwarnings(
    "ignore",
    message=r".*'audioop' is deprecated and slated for removal in Python 3\.13.*",
    category=DeprecationWarning,
)
from pydub import AudioSegment

from giga_agent.core.db import get_session_factory
from giga_agent.models.file import FileResponse
from giga_agent.modules.subagents_legacy.agents.podcast.config import (
    ConfigSchema,
    PodcastState,
)
from giga_agent.modules.subagents_legacy.agents.podcast.prompts import (
    LANGUAGE_PROMPT,
    LENGTH_MODIFIERS,
    QUESTION_MODIFIER,
    SYSTEM_PROMPT,
    TONE_MODIFIER,
    TONE_MODIFIERS,
)
from giga_agent.modules.subagents_legacy.agents.podcast.schema import (
    MediumDialogue,
    ShortDialogue,
)
from giga_agent.modules.subagents_legacy.agents.podcast.tts_sber import (
    generate_podcast_audio,
    get_sber_tts_token,
)
from giga_agent.modules.subagents_legacy.agents.podcast.utils import (
    generate_script,
    parse_url,
)
from giga_agent.modules.subagents_legacy.runtime import (
    get_current_user_from_config,
    get_user_secret,
    resolve_user_llm,
)
from giga_agent.modules.subagents_legacy.uploads import (
    build_tool_message,
    upload_files_for_config_user,
)
from giga_agent.utils.messages import filter_tool_calls


async def _resolve_llm(config: RunnableConfig):
    factory = await get_session_factory()
    async with factory() as session:
        user = await get_current_user_from_config(config, session=session)
        llm = await resolve_user_llm(user, session=session)
    return llm.with_config(tags=["nostream"])


async def download_url(state: PodcastState):
    if state.get("url"):
        return {"podcast_text": await parse_url(state["url"])}
    return {"podcast_text": ""}


async def summarize_messages(state: PodcastState, config: RunnableConfig):
    system = (
        "Ты — продюсер подкастов мирового класса, задача которого — "
        "проанализировать переписку ниже, выделить все важные моменты для подкаста и "
        "выдать детальный текст с информацией, "
        "которую потом будут использовать для подкаста"
    )
    human_mes = (
        "Проанализируй переписку и дай детальную информацию "
        "которая пригодится для подкаста"
    )
    if state.get("use_messages"):
        llm = await _resolve_llm(config)
        resp = await llm.ainvoke(
            [
                (
                    "system",
                    system,
                ),
            ]
            + state["messages"]
            + [("human", human_mes)],
        )
        return {
            "podcast_text": state.get("podcast_text", "") + "\n---\n" + resp.content,
        }
    return {}


async def script(state: PodcastState, config: RunnableConfig):
    # Модифицируем системный промпт на основе пользовательского ввода
    modified_system_prompt = SYSTEM_PROMPT
    lang_prompt = LANGUAGE_PROMPT.format(language="ru")

    if state.get("question") is not None:
        modified_system_prompt += f"\n\n{QUESTION_MODIFIER} {state.get('question')}"
    if state.get("tone") and state.get("tone") in TONE_MODIFIERS:
        modified_system_prompt += (
            f"\n\n{TONE_MODIFIER} {TONE_MODIFIERS[state.get('tone')]}."
        )
    modified_system_prompt += f"\n\n{lang_prompt}"
    if state.get("length") and state.get("length") in LENGTH_MODIFIERS:
        modified_system_prompt += f"\n\n{LENGTH_MODIFIERS[state.get('length')]}"
    llm = await _resolve_llm(config)
    if state.get("length") == "short":
        llm_output = await generate_script(
            modified_system_prompt,
            state.get("podcast_text"),
            ShortDialogue,
            llm,
        )
    else:
        llm_output = await generate_script(
            modified_system_prompt,
            state.get("podcast_text"),
            MediumDialogue,
            llm,
        )
    return {"dialogue": llm_output}


async def audio_gen(state: PodcastState, config: RunnableConfig):
    # Обрабатываем диалог
    audio_segments = []
    transcript = ""
    total_characters = 0
    llm_output = state.get("dialogue")
    factory = await get_session_factory()
    async with factory() as session:
        user = await get_current_user_from_config(config, session=session)

    for line in llm_output.dialogue:
        if line.speaker == "Ведущая (Жанна)":
            speaker_label = f"**Ведущая**: {line.text}"
        else:
            speaker_label = f"**{llm_output.name_of_guest}**: {line.text}"

        transcript += speaker_label + "\n\n"
        total_characters += len(line.text)
        sber_auth_token = get_user_secret(user, "SALUTE_SPEECH")
        salute_speech_scope = (
            get_user_secret(user, "SALUTE_SCOPE") or "SALUTE_SPEECH_PERS"
        )
        if not sber_auth_token:
            raise ValueError("SALUTE_SPEECH отсутствует в user.secrets")
        salute_access_token = await get_sber_tts_token(
            sber_auth_token,
            scope=salute_speech_scope,
        )
        try:
            audio_data = await generate_podcast_audio(
                line.text,
                salute_access_token,
                line.speaker,
            )
            if audio_data is not None:
                # Читаем аудио файл в AudioSegment
                audio_segment = AudioSegment(audio_data)
                audio_segments.append(audio_segment)

        except Exception:
            # Создаем тишину вместо аудио при ошибке
            silence = AudioSegment.silent(duration=2000)  # 2 секунды тишины
            audio_segments.append(silence)

    # Объединяем все аудио сегменты
    if audio_segments:
        combined_audio = sum(audio_segments)
    else:
        # Если нет аудио сегментов, создаем короткую тишину
        combined_audio = AudioSegment.silent(duration=1000)

    audio_file = await asyncio.to_thread(combined_audio.export, format="mp3")
    audio_bytes = await asyncio.to_thread(audio_file.read)

    uploaded = await upload_files_for_config_user(
        config,
        files=[
            {
                "file_name": f"{config['configurable']['thread_id']}/podcast.mp3",
                "file_type": "audio",
                "content": audio_bytes,
            }
        ],
    )

    return {"audio": uploaded[0].model_dump(mode="json"), "transcript": transcript}


workflow = StateGraph(PodcastState, ConfigSchema)

workflow.add_node("download", download_url)
workflow.add_node("summarize_messages", summarize_messages)
workflow.add_node("script", script)
workflow.add_node("audio_gen", audio_gen)

workflow.add_edge(START, "download")
workflow.add_edge("download", "summarize_messages")
workflow.add_edge("summarize_messages", "script")
workflow.add_edge("script", "audio_gen")
workflow.add_edge("audio_gen", "__end__")


graph = workflow.compile()


@tool
async def podcast_generate(
    url: str | None = None,
    use_messages: bool | None = None,
    runtime: ToolRuntime = None,
):
    """Создает подкаст исходя из ссылки пользователя или вашей с ним переписки
    Тебе обязательно нужно указать либо url,
    либо use_messages, либо url и use_messages для генерации подкаста

    Args:
        url: Ссылка на страницу из которой будет создан подкаст
        use_messages: Использовать переписку с пользователем для генерации подкаста?

    """

    if not url and not use_messages:
        raise ValueError("You must specify either url or use_messages!")
    conf = {
        "configurable": {
            "thread_id": str(uuid.uuid4()),
        },
    }
    push_ui_message(
        "agent_execution",
        {
            "agent": "podcast_generate",
            "node": "__start__",
            "tool_call_id": runtime.tool_call_id,
        },
    )
    input_ = {}
    if use_messages:
        input_["use_messages"] = use_messages
        last_mes = filter_tool_calls(runtime.state["messages"][-1])
        input_["messages"] = runtime.state["messages"][:-1] + [last_mes]
    if url:
        input_["url"] = url

    client = get_client()
    thread = await client.threads.create()
    thread_id = thread["thread_id"]
    state = {}
    async for chunk in client.runs.stream(
        thread_id=thread_id,
        assistant_id="podcast",
        input=input_,
        stream_mode=["values", "updates"],
        on_disconnect="cancel",
        config=conf,
    ):
        if chunk.event == "values":
            state = chunk.data
        elif chunk.event == "updates":
            push_ui_message(
                "agent_execution",
                {
                    "agent": "podcast_generate",
                    "node": list(chunk.data.keys())[0],
                    "tool_call_id": runtime.tool_call_id,
                },
            )
    audio = FileResponse.model_validate(state.get("audio"))
    return build_tool_message(
        runtime,
        tool_name="podcast_generate",
        payload={
            "transcript": state.get("transcript"),
            "message": (
                f"В результате выполнения было сгенерирован аудио-файл "
                f"{audio.sandbox_path}. "
                f"Покажи его пользователю через "
                f'"![alt-описание](attachment:{audio.sandbox_path})" '
                f"и напиши ответ с краткой информацией по подкасту"
            ),
        },
        attachments=[audio],
    )


# async def main():
#     async for event in graph.astream(
#         {
#             "url": "https://habr.com/ru/companies/sberdevices/articles/890552/",
#             "length": "short",
#         },
#         config={"configurable": {"thread_id": str(uuid.uuid4())}},
#     ):
#         print(event)
#
#
# if __name__ == "__main__":
#     asyncio.run(main())
