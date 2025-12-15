import base64
import json
import uuid

from pydantic import BaseModel, Field

from giga_agent.settings import settings
from giga_agent.utils.jupyter import JupyterClient, RunUploadFile, REPLUploader
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
    thread_id: str

    def _run(self, code: str):
        return {}

    async def _arun(self, code: str):
        client = JupyterClient()
        uploader = REPLUploader()

        response = await client.execute(self.kernel_id, code)
        result = response["result"]
        results = []
        if result is not None:
            results.append(result.strip())
        upload_files = []
        upload_resp = []
        for attachment in response["attachments"]:
            if "application/vnd.plotly.v1+json" in attachment:
                upload_files.append(
                    RunUploadFile(
                        path=f"repl/{uuid.uuid4()}.json",
                        file_type="plotly_graph",
                        content=json.dumps(
                            attachment["application/vnd.plotly.v1+json"]
                        ),
                    )
                )
            elif "image/png" in attachment:
                upload_files.append(
                    RunUploadFile(
                        path=f"repl/{uuid.uuid4()}.png",
                        file_type="image",
                        content=base64.b64decode(attachment["image/png"]),
                    )
                )
        if upload_files:
            upload_resp = await uploader.upload_run_files(upload_files, self.thread_id)
            for file in upload_resp:
                attachment_info = ""
                if file["file_type"] == "plotly_graph":
                    attachment_info = (
                        "В результате выполнения был сгенерирован график. "
                    )
                elif file["file_type"] == "image":
                    attachment_info = (
                        "В результате выполнения было сгенерировано изображение. "
                    )
                attachment_info += f"Путь до него '{file['path']}'. Ты можешь показать это пользователю с помощью через \"![alt-текст](attachment:{file['path']})\" "
                results.append(attachment_info)
        result = "\n".join(results)
        if upload_files:
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
            "giga_attachments": upload_resp,
            "is_exception": response["is_exception"],
        }
