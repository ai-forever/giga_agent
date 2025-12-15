import asyncio
from typing import List, Optional, Literal

import aiohttp
from pydantic import BaseModel

from giga_agent.settings import settings
from giga_agent.utils.types import FileContent, UploadedFile

FILE_TYPE = Literal["image", "plotly_graph", "html", "text", "audio", "other"]


class RunUploadFile(BaseModel):
    path: Optional[str] = None
    file_type: FILE_TYPE
    content: FileContent

    class Config:
        arbitrary_types_allowed = True


class KernelNotFoundException(Exception):
    pass


class REPLUploader(BaseModel):
    base_url: str = settings.internal.jupyter_upload_api

    async def upload_file(self, file):
        async with aiohttp.ClientSession() as session:
            form = aiohttp.FormData()
            # Ожидаем кортеж (filename, bytes/IO). Иные варианты добавляем как есть
            try:
                if isinstance(file, tuple) and len(file) == 2:
                    filename, content = file
                    form.add_field("file", content, filename=str(filename))
                else:
                    form.add_field("file", file)
            except Exception:
                form.add_field("file", file)

            async with session.post(
                f"{self.base_url}/upload", data=form, timeout=60.0
            ) as res:
                if res.status == 200:
                    return await res.json()
                else:
                    raise Exception(f"Error {res.status}: {res.reason}")

    async def upload_run_files(
        self,
        files: List[RunUploadFile],
        thread_id: str,
        *,
        endpoint: str = "/upload/run",
        request_timeout_seconds: int = 300,
    ) -> List[UploadedFile]:
        """Загрузка файлов в runs директорий (результаты работы агентов)"""
        url = f"{self.base_url.rstrip('/')}{endpoint if endpoint.startswith('/') else '/' + endpoint}"

        form = aiohttp.FormData()

        for file in files:
            filename = file.path
            # Если путь не указан, filename может быть None — aiohttp примет его, но серверу может понадобиться default
            form.add_field(name="files", value=file.content, filename=filename)
            form.add_field(name="types", value=file.file_type)

        form.add_field("thread_id", thread_id)

        timeout = aiohttp.ClientTimeout(total=request_timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, data=form) as resp:
                resp.raise_for_status()
                return (await resp.json()).get("saved", [])


class JupyterClient(BaseModel):
    base_url: str = settings.internal.jupyter_client_api

    async def execute(self, kernel_id, code):
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/code",
                json={"kernel_id": kernel_id, "script": code},
                timeout=60.0,
            ) as res:
                if res.status == 200:
                    data = await res.json()
                    return data
                elif res.status == 404:
                    raise KernelNotFoundException()
                else:
                    raise Exception(f"Error {res.status}: {res.reason}")

    async def start_kernel(self):
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/start",
                timeout=60.0,
            ) as res:
                if res.status == 200:
                    return await res.json()
                else:
                    raise Exception(f"Error {res.status}: {res.reason}")

    async def shutdown_kernel(self, kernel_id):
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/shutdown",
                json={"kernel_id": kernel_id},
                timeout=60.0,
            ) as res:
                if res.status == 200:
                    return await res.json()
                elif res.status == 404:
                    raise KernelNotFoundException()
                else:
                    raise Exception(f"Error {res.status}: {res.reason}")


def prepend_code(code: str, state: dict, thread_id: str, checkpoint_id: str):
    from giga_agent.config import REPL_TOOLS

    tools_code = []
    for tool in state["tools"]:
        tools_code.append(
            f"""
@tool_client.call_tool
def {tool['name']}(**kwargs):
    pass
"""
        )
    for tool in REPL_TOOLS:
        tools_code.append(
            f"""
@tool_client.call_tool
def {tool.__name__}(**kwargs):
    pass
"""
        )
    tool_url = settings.internal.tool_client_api
    prepend = f"""from app.utils import build_schema_from_json
import importlib
importlib.invalidate_caches()
import pandas as pd
import numpy as np
import datetime
from app.tool_client import ToolClient
tool_client = ToolClient(base_url='{tool_url}')
tool_client.set_state_data({repr(thread_id)}, {repr(checkpoint_id)})"""
    return prepend + "\n\n".join(tools_code) + code


if __name__ == "__main__":

    async def main():
        script = """
import pandas as pd
import numpy as np
import plotly.express as px

# Читаем CSV файл
df = pd.read_csv('files/moscow_flats_dataset.csv')

# Проверяем первые строки
print(df.head())

# Получаем общую информацию о структуре данных
print(df.info())

# Статистика по числовым признакам
print(df.describe())

# Строим гистограмму распределения цен
fig_price_hist = px.histogram(df, x='price', nbins=50, title='Распределение цен на квартиры')
fig_price_hist.show()

# Диаграмма рассеяния площади vs цена
fig_scatter_area_price = px.scatter(df, x='area', y='price', color='rooms', title='Площадь против цены квартир')
fig_scatter_area_price.show()
        """
        client = JupyterClient()
        kernel_id = (await client.start_kernel())["id"]
        response = await client.execute(kernel_id, script)
        print(response)

    asyncio.run(main())
