import io
import mimetypes
import os
import urllib.parse
import uuid
import plotly
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from langchain_gigachat import GigaChat

from langgraph_sdk import get_client


from app.settings import settings

app = FastAPI()

origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # кому разрешаем
    allow_credentials=True,  # передавать ли куки/креденшалы
    allow_methods=["*"],  # какие HTTP-методы
    allow_headers=["*"],  # какие заголовки
)

FILES_DIR = settings.files_dir
RUNS_DIR = os.environ.get("RUNS_DIR", "runs")
os.makedirs(FILES_DIR, exist_ok=True)
os.makedirs(RUNS_DIR, exist_ok=True)

llm = GigaChat(
    profanity_check=False,
    verify_ssl_certs=settings.main_gigachat_verify_ssl_certs,
    timeout=settings.repl_gigachat_timeout,
    max_tokens=settings.main_gigachat_max_tokens,
    user=settings.main_gigachat_user,
    password=settings.main_gigachat_password,
    credentials=settings.main_gigachat_credentials,
    scope=settings.main_gigachat_scope,
    base_url=settings.main_gigachat_base_url,
    top_p=settings.main_gigachat_top_p,
    verbose=settings.main_gigachat_verbose,
)
FILE_TYPES = {"image", "plotly_graph", "html", "text", "audio", "other"}

if not Path(FILES_DIR).exists():
    Path(FILES_DIR).mkdir(parents=True, exist_ok=True)


def uniquify(path):
    filename, extension = os.path.splitext(path)
    counter = 1

    while os.path.exists(path):
        path = filename + " (" + str(counter) + ")" + extension
        counter += 1

    return path


def _safe_join(base: str, relative: str) -> str:
    relative = (relative or "").replace("\\", "/").lstrip("/")
    candidate = os.path.normpath(os.path.join(base, relative))
    base_abs = os.path.abspath(base)
    cand_abs = os.path.abspath(candidate)
    if not (cand_abs == base_abs or cand_abs.startswith(base_abs + os.sep)):
        raise HTTPException(status_code=400, detail="Недопустимый путь")
    return candidate


def _detect_image_mime(path: str) -> Optional[str]:
    try:
        from PIL import Image

        with Image.open(path) as img:
            img.verify()
            mime = Image.MIME.get(img.format)
            return mime
    except Exception:
        return None


async def upload_image(path: str) -> dict:
    from PIL import Image, ImageOps
    import httpx

    api_url_base = os.getenv("GIGA_AGENT_API", "").rstrip("/")
    if not api_url_base:
        raise RuntimeError("GIGA_AGENT_API is not set")
    url = f"{api_url_base}/upload/image/"

    # Определяем, является ли исходный файл JPEG
    is_jpeg = False
    try:
        with Image.open(path) as im:
            is_jpeg = im.format == "JPEG"
    except Exception:
        is_jpeg = path.lower().endswith((".jpg", ".jpeg"))

    if is_jpeg:
        # Если уже JPEG — отправляем как есть, без перекодирования
        async with httpx.AsyncClient(timeout=60) as client:
            with open(path, "rb") as f:
                response = await client.post(
                    url,
                    files={
                        "file": (
                            os.path.basename(path),
                            f,
                            "image/jpeg",
                        )
                    },
                )
        response.raise_for_status()
        return response.json()

    # Иначе конвертируем в JPEG и уменьшаем при необходимости
    image = ImageOps.exif_transpose(Image.open(path))
    max_side = 1024
    if max(image.size) > max_side:
        image.thumbnail((max_side, max_side), Image.LANCZOS)

    buf = io.BytesIO()
    image.convert("RGB").save(
        buf,
        format="JPEG",
        quality=85,
        optimize=True,
        progressive=True,
    )
    buf.seek(0)

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            url,
            files={
                "file": (
                    f"{uuid.uuid4()}.jpg",
                    buf,
                    "image/jpeg",
                )
            },
        )
    response.raise_for_status()
    return response.json()


@app.post("/upload/run")
async def upload_run(
    files: List[UploadFile] = File(...),
    paths: Optional[List[str]] = Form(default=None),
    types: List[str] = Form(...),
    thread_id: str = Form(...),
):
    saved = []
    # Валидация соответствия размеров списков
    if not types or len(types) != len(files):
        raise HTTPException(
            status_code=400,
            detail="Количество элементов 'types' должно совпадать с количеством 'files'",
        )
    try:
        for idx, file in enumerate(files):
            if paths and idx < len(paths) and paths[idx]:
                rel = paths[idx]
            else:
                rel = file.filename

            rel = urllib.parse.unquote(rel)
            dest_path = _safe_join(_safe_join(RUNS_DIR, thread_id), rel)
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)

            with open(dest_path, "wb") as out:
                while chunk := await file.read(1024 * 1024):
                    out.write(chunk)

            # Определяем тип файла на основе обязательного параметра
            t = (types[idx] or "").strip().lower()
            if t not in FILE_TYPES:
                raise HTTPException(status_code=400, detail=f"Недопустимый тип: {t}")
            file_type = t
            image_id = None
            image_path = None
            if file_type == "image":
                data = await upload_image(dest_path)
                image_id = data["id"]
                image_path = dest_path
            elif file_type == "plotly_graph":
                with open(dest_path, "r") as f:
                    plot_json = f.read()
                plot = plotly.io.from_json(plot_json)
                img = plotly.io.to_image(plot, format="jpg")
                img_path = ".".join(dest_path.split(".")[:-1]) + ".jpg"
                with open(img_path, "wb") as f:
                    f.write(img)
                data = await upload_image(img_path)
                image_id = data["id"]
                image_path = img_path
            file_metadata = {
                "path": dest_path,
                "size": os.path.getsize(dest_path),
                "file_type": file_type,
                "image_id": image_id,
                "image_path": image_path,
            }
            saved.append(file_metadata)
            client = get_client(
                url=os.getenv("LANGGRAPH_API_URL", "http://0.0.0.0:2024")
            )
            await client.store.put_item(
                ("attachments",),
                dest_path,
                file_metadata,
                ttl=None,
                index=False,
            )
    finally:
        for f in files:
            await f.close()
    return {"saved": saved}


@app.post("/upload/")
async def upload(file: UploadFile = File(...)):
    try:
        path = uniquify(_safe_join(FILES_DIR, file.filename))
        with open(path, "wb") as f:
            while contents := file.file.read(1024 * 1024):
                f.write(contents)
        if file.content_type.startswith("image/"):
            data = await upload_image(path)
            file_metadata = {
                "path": path,
                "size": os.path.getsize(path),
                "file_type": "image",
                "image_id": data.get("id"),
                "image_path": path,
            }
            client = get_client(
                url=os.getenv("LANGGRAPH_API_URL", "http://0.0.0.0:2024")
            )
            await client.store.put_item(
                ("attachments",),
                path,
                file_metadata,
                ttl=None,
                index=False,
            )
            return file_metadata
    except Exception as e:
        raise e
    finally:
        file.file.close()

    return {"path": path}


@app.get("/files/{filename}")
def download_file(filename: str):
    # Нормализуем путь и защищаемся от path traversal
    file_path = os.path.normpath(os.path.join(FILES_DIR, filename))
    if not file_path.startswith(FILES_DIR) or not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="Файл не найден")

    # Определяем MIME-тип по расширению
    mime_type, _ = mimetypes.guess_type(file_path)
    if not mime_type:
        mime_type = "application/octet-stream"

    # Выбираем режим отдачи: inline для image/* и application/pdf, иначе attachment
    if mime_type.startswith("image/") or mime_type == "application/pdf":
        disposition = "inline"
    else:
        disposition = "attachment"

    return FileResponse(
        path=file_path,
        media_type=mime_type,
        headers={
            "Content-Disposition": f'{disposition}; filename="{os.path.basename(file_path)}"'
        },
    )
