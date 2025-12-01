import asyncio
import io
import json
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse
from sqlmodel import SQLModel, Field, select, func
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import sessionmaker

from langgraph_sdk import get_client

from giga_agent.utils.env import load_project_env
from giga_agent.utils.llm import is_llm_image_inline, upload_file_with_retry
from giga_agent.utils.memory import get_memory

load_project_env()


# --- Модель данных ---
class Task(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    json_data: str = Field(default_factory=lambda: str("{}"))
    steps: int = Field(default=10, nullable=False)
    sorting: int = Field(default=None, nullable=False, index=True)
    active: bool = Field(default=False, nullable=False)


Path("db").mkdir(parents=True, exist_ok=True)


# --- Настройка асинхронного движка и сессии ---
DATABASE_URL = "sqlite+aiosqlite:///db/tasks.db"
engine: AsyncEngine = create_async_engine(
    DATABASE_URL, echo=True, connect_args={"check_same_thread": False}
)
AsyncSessionLocal = sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False
)


# --- Создаем таблицы ---
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async with AsyncSessionLocal() as session:
        # Считаем, сколько строк в таблице Task
        result = await session.execute(select(func.count()).select_from(Task))
        count_tasks = result.scalar_one()  # возвращает 0, если пусто
        # Если таблица Task пуста, подгружаем JSON-дамп
        if count_tasks == 0:
            # Предположим, файл dump.json лежит в той же директории, что и скрипт
            dump_path = os.path.join(os.path.dirname(__file__), "dump.json")
            if os.path.exists(dump_path):
                # Читаем список объектов из JSON
                with open(dump_path, "r", encoding="utf-8") as f:
                    data_list = await asyncio.to_thread(json.load, fp=f)

                # Проходим по каждому элементу массива
                for item in data_list:
                    # Извлекаем поля из JSON-объекта.
                    # Если в JSON не указан id, сгенерируем новый.
                    _id = item.get("id", str(uuid4()))

                    # Если в дампе json_data — это вложенный объект,
                    # сериализуем его в строку:
                    _json_data = item.get("json_data", {})
                    json_str = json.dumps(_json_data, ensure_ascii=False)

                    # Считываем остальные поля, или ставим дефолт
                    _steps = item.get("steps", 10)
                    _sorting = item.get("sorting", None)
                    _active = item.get("active", False)

                    # Если sorting не указан в JSON или равен None,
                    # можно установить next_sorting
                    if _sorting is None:
                        # Здесь мы вызываем вашу функцию next_sorting,
                        # передавая текущую сессию
                        _sorting = await next_sorting(session)

                    # Создаём объект Task и добавляем в сессию
                    task = Task(
                        id=_id,
                        json_data=json_str,
                        steps=_steps,
                        sorting=_sorting,
                        active=_active,
                    )
                    session.add(task)

                await session.commit()
            else:
                print(f"Файл {dump_path} не найден, пропускаем загрузку")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    # Clean up connections


# Запускаем инициализацию при старте
app = FastAPI(lifespan=lifespan)


# Вспомогательная функция для получения следующего sorting
async def next_sorting(session: AsyncSession) -> int:
    result = await session.execute(select(func.max(Task.sorting)))
    max_sort = result.scalar_one_or_none()
    return (max_sort or 0) + 1


# 1) Создать задачу
@app.post("/tasks/", response_model=Task)
async def create_task():
    async with AsyncSessionLocal() as session:
        task = Task(json_data=json.dumps({"message": "", "attachments": []}))
        task.sorting = await next_sorting(session)
        session.add(task)
        await session.commit()
        await session.refresh(task)
        return task


# 2) Получить все задачи (сортируя по полю sorting)
@app.get("/tasks/")
async def list_tasks():
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Task).order_by(Task.sorting))
        tasks = result.scalars().all()
        new_tasks = []
        for task in tasks:
            new_task = task.dict()
            new_task["json_data"] = json.loads(task.json_data)
            new_tasks.append(new_task)
        return new_tasks


# 3) Получить конкретную задачу
@app.get("/tasks/{task_id}/", response_model=Task)
async def get_task(task_id: str):
    async with AsyncSessionLocal() as session:
        task = await session.get(Task, task_id)
        if not task:
            raise HTTPException(404, "Task not found")
        return task


# 4) Обновить задачу (json_data и/или steps)
class TaskUpdate(SQLModel):
    json_data: Optional[dict] = None
    steps: Optional[int] = None
    sorting: Optional[int] = None
    active: Optional[bool] = None


@app.put("/tasks/{task_id}/", response_model=Task)
async def update_task(task_id: str, task_update: TaskUpdate):
    async with AsyncSessionLocal() as session:
        task = await session.get(Task, task_id)
        if not task:
            raise HTTPException(404, "Task not found")
        if task_update.json_data is not None:
            task.json_data = json.dumps(task_update.json_data, ensure_ascii=False)
        if task_update.steps is not None:
            task.steps = task_update.steps
        if task_update.sorting is not None:
            task.sorting = task_update.sorting
        if task_update.active is not None:
            task.active = task_update.active
        session.add(task)
        await session.commit()
        await session.refresh(task)
        return task


# 5) Удалить задачу
@app.delete("/tasks/{task_id}/", status_code=204)
async def delete_task(task_id: str):
    async with AsyncSessionLocal() as session:
        task = await session.get(Task, task_id)
        if not task:
            raise HTTPException(404, "Task not found")
        await session.delete(task)
        await session.commit()


@app.get("/html/{html_id}/", response_class=HTMLResponse)
async def get_html(html_id: str):
    client = get_client(url=os.getenv("LANGGRAPH_API_URL", "http://0.0.0.0:2024"))
    result = await client.store.get_item(("html",), key=html_id)
    if result:
        return HTMLResponse(content=result["value"]["data"], status_code=200)
    else:
        raise HTTPException(404, "Page not found")


@app.post("/upload/image/")
async def upload_image(file: UploadFile = File(...)):
    file_bytes = await file.read()
    if is_llm_image_inline():
        uploaded_id = await upload_file_with_retry(
            (
                f"{uuid.uuid4()}.jpg",
                io.BytesIO(file_bytes),
            )
        )
    else:
        uploaded_id = str(uuid.uuid4())
    return {"id": uploaded_id}

@app.get("/memories")
async def get_memories():
    memory = await get_memory()
    results = await memory.get_all(user_id="default_user")
    return results

