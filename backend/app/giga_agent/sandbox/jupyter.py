import json
import uuid
from typing import AsyncGenerator, Dict, Any, Optional
import aiohttp
import websockets
from pydantic import Field, PrivateAttr

from giga_agent.sandbox.base import BaseSandbox
from giga_agent.sandbox.mixins.code import CodeMixin


class JupyterSandbox(BaseSandbox, CodeMixin):
    base_url: str = Field(..., description="Base URL of the Jupyter server")
    headers: Optional[Dict[str, str]] = Field(
        default_factory=dict, description="Additional headers"
    )

    _kernel_id: Optional[str] = PrivateAttr(default=None)
    _token: str = PrivateAttr(default="")

    def _get_headers(self) -> Dict[str, str]:
        headers = {"Authorization": f"token {self._token}"}
        if self.headers:
            headers.update(self.headers)
        return headers

    async def up(self) -> None:
        """
        JupyterSandbox подключается к уже существующему экземпляру,
        поэтому метод up не выполняет действий по запуску.
        """
        pass

    async def is_up(self) -> bool:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/api/status",
                    headers=self._get_headers(),
                    timeout=5,
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get("started", False) is not False
        except Exception:
            pass
        return False

    async def _ensure_kernel(self):
        async with aiohttp.ClientSession() as session:
            if self._kernel_id:
                # Check if alive
                try:
                    async with session.get(
                        f"{self.base_url}/api/kernels/{self._kernel_id}",
                        headers=self._get_headers(),
                    ) as r:
                        if r.status == 200:
                            return
                except Exception:
                    pass

            # Create new kernel
            async with session.post(
                f"{self.base_url}/api/kernels", headers=self._get_headers()
            ) as r:
                r.raise_for_status()
                data = await r.json()
                self._kernel_id = data["id"]

    async def run_code(self, code: str) -> AsyncGenerator[Dict[str, Any], str]:
        await self._ensure_kernel()

        # Connect to websocket
        ws_url = self.base_url.replace("http", "ws")
        url = f"{ws_url}/api/kernels/{self._kernel_id}/channels?token={self._token}"

        async with websockets.connect(url, additional_headers=self.headers) as ws:
            msg_id = uuid.uuid4().hex

            msg = {
                "header": {
                    "msg_id": msg_id,
                    "username": "giga_agent",
                    "session": uuid.uuid4().hex,
                    "msg_type": "execute_request",
                    "version": "5.3",
                },
                "parent_header": {},
                "metadata": {},
                "content": {
                    "code": code,
                    "silent": False,
                    "store_history": True,
                    "user_expressions": {},
                    "allow_stdin": True,
                    "stop_on_error": True,
                },
                "channel": "shell",
            }

            await ws.send(json.dumps(msg))

            async for message in ws:
                response = json.loads(message)
                msg_type = response["msg_type"]
                parent_msg_id = response.get("parent_header", {}).get("msg_id")

                if parent_msg_id != msg_id:
                    continue

                content = response["content"]

                if msg_type == "stream":
                    yield {
                        "type": content["name"],  # stdout or stderr
                        "text": content["text"],
                    }
                elif msg_type == "execute_result":
                    yield {
                        "type": "result",
                        "data": content["data"],
                        "execution_count": content["execution_count"],
                    }
                elif msg_type == "error":
                    yield {
                        "type": "error",
                        "ename": content["ename"],
                        "evalue": content["evalue"],
                        "traceback": content["traceback"],
                    }
                elif msg_type == "display_data":
                    yield {
                        "type": "display_data",
                        "data": content["data"],
                    }
                elif msg_type == "input_request":
                    # Wait for input from the consumer of the generator
                    user_input = yield {
                        "type": "input_request",
                        "prompt": content.get("prompt", ""),
                        "password": content.get("password", False),
                    }

                    input_reply = {
                        "header": {
                            "msg_id": uuid.uuid4().hex,
                            "username": "giga_agent",
                            "session": uuid.uuid4().hex,
                            "msg_type": "input_reply",
                            "version": "5.3",
                        },
                        "parent_header": response["header"],
                        "metadata": {},
                        "content": {
                            "value": str(user_input) if user_input is not None else ""
                        },
                        "channel": "stdin",
                    }
                    await ws.send(json.dumps(input_reply))

                elif msg_type == "status":
                    if content["execution_state"] == "idle":
                        break
