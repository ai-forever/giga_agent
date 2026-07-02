import json
import uuid
from typing import Any, AsyncGenerator, Optional, Dict
import aiohttp
import websockets
from pydantic import Field, PrivateAttr

from giga_agent.sandbox.base import BaseSandbox
from giga_agent.sandbox.mixins.code import CodeMixin

WS_MAX_SIZE = 32 * 1024 * 1024


def _inject_env_prelude(code: str, envs: dict[str, str] | None) -> str:
    if envs is None:
        return code

    managed_envs = {str(key): str(value) for key, value in envs.items()}
    envs_json = json.dumps(managed_envs, ensure_ascii=False)
    prelude = "\n".join(
        [
            "import json as _giga_agent_json",
            "import os as _giga_agent_os",
            f"_giga_agent_envs = _giga_agent_json.loads({envs_json!r})",
            "_giga_agent_key = None",
            "_giga_agent_value = None",
            "for _giga_agent_key, _giga_agent_value in _giga_agent_envs.items():",
            "    _giga_agent_os.environ[_giga_agent_key] = _giga_agent_value",
            "del _giga_agent_key, _giga_agent_value",
            "del _giga_agent_envs, _giga_agent_json, _giga_agent_os",
            "",
        ]
    )
    return prelude + code


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

    def _get_kernel_request_payload(self) -> Dict[str, Any] | None:
        return None

    def is_base_url_internal(self) -> bool:
        return False

    def _get_client_session_kwargs(self) -> Dict[str, Any]:
        if self.is_base_url_internal():
            return {"trust_env": False}
        return {}

    def _get_websocket_connect_kwargs(self) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {}
        if self.is_base_url_internal():
            kwargs["proxy"] = None
        open_timeout = self._kernel_startup_timeout()
        if open_timeout is not None:
            # The server finishes the WS opening handshake only once the kernel
            # is connected, so this doubles as the kernel-ready budget.
            kwargs["open_timeout"] = open_timeout
        return kwargs

    def _kernel_startup_timeout(self) -> float | None:
        """Seconds allotted for a kernel to come up (POST + WS handshake).

        ``None`` keeps library defaults (``websockets`` ≈10s, ``aiohttp`` ≈300s).
        Subclasses (e.g. the managed local sandbox) override with a configured
        value so cold/contended kernel launches don't fail spuriously.
        """
        return None

    async def up(self) -> None:
        """
        JupyterSandbox подключается к уже существующему экземпляру,
        поэтому метод up не выполняет действий по запуску.
        """
        pass

    async def is_up(self) -> bool:
        try:
            async with aiohttp.ClientSession(
                **self._get_client_session_kwargs()
            ) as session:
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

    async def _before_kernel_create(self, session: aiohttp.ClientSession) -> None:
        """Hook invoked right before a brand new kernel is created."""
        del session

    async def _on_kernel_active(self, kernel_id: str) -> None:
        """Hook invoked whenever a kernel is created or reused."""
        del kernel_id

    async def _ensure_kernel(self) -> None:
        session_kwargs = dict(self._get_client_session_kwargs())
        kernel_timeout = self._kernel_startup_timeout()
        if kernel_timeout is not None:
            # Bound the kernel-creation POST too: the server blocks it until the
            # kernel is ready, so without this it hangs on aiohttp's ~300s default.
            session_kwargs["timeout"] = aiohttp.ClientTimeout(total=kernel_timeout)
        async with aiohttp.ClientSession(**session_kwargs) as session:
            if self._kernel_id:
                # Check if alive
                try:
                    async with session.get(
                        f"{self.base_url}/api/kernels/{self._kernel_id}",
                        headers=self._get_headers(),
                    ) as r:
                        if r.status == 200:
                            await self._on_kernel_active(self._kernel_id)
                            return
                except Exception:
                    pass

            # Create new kernel
            await self._before_kernel_create(session)
            payload = self._get_kernel_request_payload()
            async with session.post(
                f"{self.base_url}/api/kernels",
                headers=self._get_headers(),
                json=payload,
            ) as r:
                r.raise_for_status()
                data = await r.json()
                self._kernel_id = data["id"]
            await self._on_kernel_active(self._kernel_id)

    async def run_code(
        self,
        code: str,
        kernel_id: str | None = None,
        *,
        allow_stdin: bool = True,
        envs: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[dict[str, Any], str]:
        del kwargs
        code = _inject_env_prelude(code, envs)
        if kernel_id is None:
            self._kernel_id = str(uuid.uuid4())
        else:
            self._kernel_id = kernel_id
        await self._ensure_kernel()

        # Connect to websocket
        ws_url = self.base_url.replace("http", "ws")
        url = f"{ws_url}/api/kernels/{self._kernel_id}/channels?token={self._token}"

        async with websockets.connect(
            url,
            additional_headers=self.headers,
            max_size=WS_MAX_SIZE,
            **self._get_websocket_connect_kwargs(),
        ) as ws:
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
                    "allow_stdin": allow_stdin,
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
