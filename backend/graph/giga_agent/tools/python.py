import asyncio
import json
import uuid
from base64 import b64decode, b64encode

import plotly
from pydantic import BaseModel, Field

from giga_agent.utils.llm import is_llm_image_inline, load_llm
from giga_agent.settings import settings
from giga_agent.utils.jupyter import JupyterClient
from langchain_core.tools import BaseTool
import re


class CodeInput(BaseModel):
    code: str = Field(..., description="Код Python")


INPUT_REGEX = re.compile(r"input\(.+?\)")
FILE_NOT_FOUND_REGEX = re.compile(r"FileNotFoundError:.+?No such file or directory")


class ExecuteTool(BaseTool):
    name: str = "python"
    description: str = (
        "Компилятор ipython. Возвращает результат выполнения. "
        "Если произошла ошибка напиши исправленный код "
    )
    kernel_id: str

    def _run(self, code: str):
        return {}

    async def _arun(self, code: str):
        client = JupyterClient(base_url=settings.internal.jupyter_client_api)

        if INPUT_REGEX.search(code):
            return {
                "message": (
                    "Перепиши код без использования функции input. "
                    "Сгенерируй синтетические данные сам"
                ),
                "giga_attachments": [],
                "is_exception": True,
            }

        response = await client.execute(self.kernel_id, code)
        result = response["result"]
        results = []
        if result is not None:
            results.append(result.strip())
        file_ids = []
        have_images = False
        attachments = []
        for attachment in response["attachments"]:
            img = None
            attachment_info = ""
            attachment_data = {}
            if "application/vnd.plotly.v1+json" in attachment:
                attachment_info = "В результате выполнения был сгенерирован график."
                results.append(
                    "В результате выполнения был сгенерирован график. "  # Он показан пользователю.
                )
                data = json.dumps(attachment["application/vnd.plotly.v1+json"])
                plot = plotly.io.from_json(data)
                img = await asyncio.to_thread(plotly.io.to_image, plot, format="png")
                attachment_data["type"] = "application/vnd.plotly.v1+json"
                attachment_data["data"] = attachment["application/vnd.plotly.v1+json"]
            elif "image/png" in attachment:
                attachment_info = "В результате выполнения было сгенерировано изображение. "  # . Оно показано пользователю.
                img = b64decode(attachment["image/png"])
                attachment_data["type"] = "image/png"
                attachment_data["data"] = attachment["image/png"]
            if img is not None:
                have_images = True
                if is_llm_image_inline():
                    llm = load_llm()
                    uploaded_file_id = (await llm.aupload_file(("image.png", img))).id_
                else:
                    uploaded_file_id = str(uuid.uuid4())
                attachment_data["img_data"] = b64encode(img)
                attachment_data["file_id"] = uploaded_file_id
                attachment_info += f"ID изображения '{uploaded_file_id}'. Ты можешь показать это пользователю с помощью через \"![График](graph:{uploaded_file_id})\" "
                results.append(attachment_info)
                attachments.append(attachment_data)
        result = "\n".join(results)
        if have_images:
            result += "\nНе забывай, что у тебя есть анализ изображений. С помощью анализа ты можешь сравнить то, что ты ожидал получить в графике с тем что получилось на деле!\nТакже не забывай, что ты ОБЯЗАН вывести изображения/графики пользователю при формировании финального ответа!"
        if response["is_exception"]:
            # Убираем лишние строки кода из ошибки, для улучшения качества исправления
            exc = re.sub(
                r"(.+?\/.+?py.+\n(.+\n)+\n)", "", response["exception"], 0, re.MULTILINE
            )
            message = (
                f'Результат выполнения: "{result.strip()}".\n Во время исполнения кода произошла ошибка: "{exc}"!!.\n'
                "Исправь ошибку."
            )
            if "KeyboardInterrupt" in exc:
                message += "Твой код выполнялся слишком долго! Разбей его на более простые шаги, чтобы он выполнялся меньше 40 секунд, или поменяй алгоритм решения задачи на более оптимальный!"
        else:
            message = (
                f'Результат выполнения: "{result.strip()}". Код выполнился без ошибок. Проверь нужные переменные. Не забудь, что пользователь не видит этот результат, поэтому если нужно перепиши его.\n'
                "Сверься со своим планом. Помни, что тебе нужно выполнить всю задачу пользователя, поэтому не спеши со своим ответом. Твой следующий шаг: "
            )
        # if len(result.strip()) > 12000:
        #     message = "Результат выполнения вышел слишком длинным. Выводи меньше информации. Допустим не пиши значения"
        return {
            "message": message,
            "giga_attachments": attachments,
            "is_exception": response["is_exception"],
        }
