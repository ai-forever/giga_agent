import base64
import json
import mimetypes
import uuid

from giga_agent.utils.jupyter import REPLUploader, RunUploadFile


async def process_mcp_content(content_list: list, thread_id: str):
    upload_files = []
    text_parts = []
    for content in content_list:
        if content.get("type") in ["image", "audio"]:
            mime_type = content["mimeType"]
            common_mime_map = {
                "audio/wav": ".wav",
                "audio/x-wav": ".wav",
                "image/jpeg": ".jpg",
                "image/png": ".png",
                "image/gif": ".gif",
                "audio/mpeg": ".mp3",
                "audio/mp3": ".mp3",
                "video/mp4": ".mp4",
            }
            file_extension = common_mime_map.get(mime_type)
            if not file_extension:
                file_extension = mimetypes.guess_extension(mime_type)
            if content.get("type") == "image":
                upload_files.append(
                    RunUploadFile(
                        path=f"mcp/{uuid.uuid4()}{file_extension}",
                        file_type="image",
                        content=base64.b64decode(content.get("data")),
                    ),
                )
            elif content.get("type") == "audio":
                upload_files.append(
                    RunUploadFile(
                        path=f"mcp/{uuid.uuid4()}{file_extension}",
                        file_type="audio",
                        content=base64.b64decode(content.get("data")),
                    ),
                )
        elif content.get("type") == "text":
            try:
                text_parts.append(json.loads(content.get("text")))
            except json.JSONDecodeError:
                text_parts.append(content.get("text"))
    message_parts = []
    upload_resp = []
    if upload_files:
        uploader = REPLUploader()
        upload_resp = await uploader.upload_run_files(upload_files, thread_id)
        for file in upload_resp:
            attachment_info = ""
            if file["file_type"] == "audio":
                attachment_info = (
                    "В результате выполнения был сгенерирован аудио-файл. "
                )
            elif file["file_type"] == "image":
                attachment_info = (
                    "В результате выполнения было сгенерировано изображение. "
                )
            attachment_info += (
                f"Путь до него '{file['path']}'."
                f"Ты можешь показать это пользователю с помощью через "
                f'"![alt-текст](attachment:{file["path"]})" '
            )
            message_parts.append(attachment_info)
    message = "\n".join(message_parts)
    if len(text_parts) == 1:
        result = text_parts[0]
    else:
        result = text_parts
    return result, upload_resp, message
