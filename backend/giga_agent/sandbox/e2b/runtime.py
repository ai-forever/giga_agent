"""E2BSandbox — E2B Cloud-backed Jupyter sandbox runtime."""

import asyncio
import secrets
import shlex
import time
import uuid
from collections.abc import AsyncGenerator
from typing import Any, Optional

from pydantic import Field, PrivateAttr

from giga_agent.core.logging import get_logger
from giga_agent.sandbox.e2b.constants import JUPYTER_PORT, S3_MOUNT_PREFIX
from giga_agent.sandbox.e2b.files import S3FilesMixin
from giga_agent.sandbox.e2b.shell import E2BShellMixin
from giga_agent.sandbox.jupyter import JupyterSandbox
from giga_agent.sandbox.registry import SandboxRegistry

logger = get_logger(__name__)


@SandboxRegistry.register("e2b")
class E2BSandbox(E2BShellMixin, S3FilesMixin, JupyterSandbox):
    """
    Песочница на базе E2B Cloud.

    Создаёт облачный sandbox через E2B SDK, настраивает S3 FUSE mount
    и запускает Jupyter Server для выполнения кода.

    Все настройки берутся из provider_settings / sandbox settings:
    - api_key: API ключ E2B
    - template: шаблон E2B (default: "jupyter-server")
    - s3_bucket: имя S3 бакета для FUSE mount
    - s3_endpoint: endpoint S3
    - s3_region: регион S3
    - aws_access_key_id: AWS access key
    - aws_secret_access_key: AWS secret key
    - idle_timeout: таймаут жизни sandbox в E2B (секунды), прокидывается из провайдера
    """

    # --- Settings (приходят из provider_settings) ---
    api_key: str = Field(..., description="E2B API key")
    template: str = Field(
        default="murtazkorpaz/jupyter-server", description="E2B sandbox template"
    )
    idle_timeout: int = Field(
        default=300, description="Sandbox timeout in seconds (from provider)"
    )
    owner_id: Optional[uuid.UUID] = Field(
        default=None, description="Sandbox owner id (runtime only)"
    )

    # S3 FUSE настройки (обязательные)
    s3_bucket: str = Field(..., description="S3 bucket name")
    s3_endpoint: str = Field(..., description="S3 endpoint URL")
    s3_region: str = Field(..., description="S3 region")
    aws_access_key_id: str = Field(..., description="AWS access key")
    aws_secret_access_key: str = Field(..., description="AWS secret key")

    # --- Connection settings (сохраняются после up, восстанавливаются из БД) ---
    external_id: Optional[str] = Field(default=None, description="E2B sandbox ID")
    jupyter_token: Optional[str] = Field(default=None, description="Jupyter auth token")

    # Override: base_url вычисляется после создания sandbox
    base_url: str = Field(
        default="", description="Base URL (set after sandbox creation)"
    )

    # Исключаем connection-поля из provider settings schema
    _runtime_fields = JupyterSandbox._runtime_fields | {"jupyter_token", "owner_id"}

    # --- Private ---
    _e2b_sandbox: Any = PrivateAttr(default=None)
    _s3_prefix_ready: bool = PrivateAttr(default=False)

    def model_post_init(self, __context: Any) -> None:
        if self.jupyter_token:
            self._token = self.jupyter_token

    def get_connection_settings(self) -> dict:
        return {
            "external_id": self.external_id,
            "jupyter_token": self._token,
        }

    @staticmethod
    def get_tools() -> list:
        from giga_agent.sandbox.e2b.tools import open_port

        return [open_port]

    # ------------------------------------------------------------------
    # settings validation
    # ------------------------------------------------------------------

    @classmethod
    async def validate_settings(cls, settings: dict) -> dict:
        validated = await super().validate_settings(settings)

        api_key = validated.get("api_key", "")
        if not api_key or not api_key.strip():
            raise ValueError("api_key is required and must not be empty")

        await cls._check_e2b_api_key(api_key)

        s3_fields = (
            "s3_bucket",
            "s3_endpoint",
            "s3_region",
            "aws_access_key_id",
            "aws_secret_access_key",
        )
        missing = [f for f in s3_fields if not validated.get(f, "").strip()]
        if missing:
            raise ValueError(
                f"S3 configuration is required. Missing: {', '.join(sorted(missing))}"
            )
        await cls._check_s3_connection(validated)

        return validated

    @staticmethod
    async def _check_e2b_api_key(api_key: str) -> None:
        from e2b import AsyncSandbox

        try:
            await AsyncSandbox.list(api_key=api_key).next_items()
        except Exception as e:
            raise ValueError(f"E2B API key validation failed: {e}") from e

    @staticmethod
    async def _check_s3_connection(settings: dict) -> None:
        import aioboto3
        from botocore.exceptions import BotoCoreError, ClientError

        session = aioboto3.Session()
        try:
            async with session.client(
                "s3",
                endpoint_url=settings["s3_endpoint"],
                region_name=settings["s3_region"],
                aws_access_key_id=settings["aws_access_key_id"],
                aws_secret_access_key=settings["aws_secret_access_key"],
            ) as s3:
                await s3.head_bucket(Bucket=settings["s3_bucket"])
        except (BotoCoreError, ClientError) as e:
            raise ValueError(
                f"S3 connection check failed for bucket '{settings['s3_bucket']}': {e}"
            ) from e

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    async def up(self) -> None:
        """Create E2B sandbox and mount S3. Jupyter is started lazily."""
        from e2b import AsyncSandbox

        self._token = secrets.token_urlsafe(13)
        self.jupyter_token = self._token

        envs = {
            "JUPYTER_TOKEN": self._token,
            "MATPLOTLIBRC": "/root/.config/matplotlib/.matplotlibrc",
            "AWSACCESSKEYID": self.aws_access_key_id,
            "AWSSECRETACCESSKEY": self.aws_secret_access_key,
        }

        logger.info(f"Creating E2B sandbox (template={self.template})...")

        self._e2b_sandbox = await AsyncSandbox.create(
            template=self.template,
            envs=envs,
            timeout=self.idle_timeout,
            api_key=self.api_key,
        )

        self.external_id = self._e2b_sandbox.sandbox_id
        logger.info(f"E2B sandbox created: {self.external_id}")

        await self._ensure_user_prefix_exists()
        await self._mount_s3()

        host = self._e2b_sandbox.get_host(JUPYTER_PORT)
        self.base_url = f"https://{host}"
        logger.info(f"E2B sandbox ready, Jupyter will be at: {self.base_url}")

    async def _mount_s3(self) -> None:
        owner_id = self._require_owner_id()
        bucket_with_prefix = f"{self.s3_bucket}:/{self._user_s3_prefix(owner_id)}"
        logger.info(f"Mounting S3 prefix '{bucket_with_prefix}'...")

        await self._e2b_sandbox.commands.run(
            f"mkdir -p {S3_MOUNT_PREFIX}",
            user="root",
        )
        await self._e2b_sandbox.commands.run(
            f"chmod 0777 {S3_MOUNT_PREFIX}",
            user="root",
        )

        s3_cmd_parts = [
            f"s3fs {shlex.quote(bucket_with_prefix)} {shlex.quote(S3_MOUNT_PREFIX)}",
            f"-o url={self.s3_endpoint}",
            f"-o endpoint={self.s3_region}",
            "-o use_path_request_style",
            "-o allow_other",
            "-o umask=000",
            "-o mp_umask=000",
            "-o default_permissions",
        ]

        s3_cmd = " ".join(s3_cmd_parts)
        result = await self._e2b_sandbox.commands.run(s3_cmd, user="root")

        if result.exit_code != 0:
            logger.warning(f"S3 mount failed: {result.stderr}")
        else:
            logger.info("S3 mounted successfully")

    # ------------------------------------------------------------------
    # lazy Jupyter start (triggered by run_code)
    # ------------------------------------------------------------------

    async def _is_jupyter_ready(self) -> bool:
        if not self.base_url:
            return False
        return await super().is_up()

    async def _start_jupyter_server(self) -> None:
        await self._ensure_e2b_sandbox_connected()
        logger.info("Starting Jupyter Server in E2B sandbox...")
        await self._e2b_sandbox.commands.run(
            f"jupyter server --ip=0.0.0.0 --port={JUPYTER_PORT} > /dev/null 2>&1",
            background=True,
        )

    async def _wait_for_jupyter(self, timeout_seconds: int = 15) -> None:
        start_time = time.time()
        while True:
            if await self._is_jupyter_ready():
                logger.info("Jupyter is up and connected")
                return

            if time.time() - start_time > timeout_seconds:
                raise TimeoutError(
                    f"Jupyter did not start within {timeout_seconds} seconds"
                )
            logger.debug("Waiting for Jupyter...")
            await asyncio.sleep(1)

    async def _ensure_jupyter_ready(self) -> bool:
        if await self._is_jupyter_ready():
            return False
        await self._start_jupyter_server()
        await self._wait_for_jupyter()
        return True

    async def run_code(
        self,
        code: str,
        kernel_id: str | None = None,
        *,
        allow_stdin: bool = True,
        envs: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[dict[str, Any], str]:
        jupyter_started = await self._ensure_jupyter_ready()
        effective_kernel_id = kernel_id
        if jupyter_started:
            logger.info(
                "Jupyter was started lazily for E2B sandbox %s; resetting kernel state",
                self.external_id,
            )
            self._kernel_id = None
            effective_kernel_id = None

        async for chunk in super().run_code(
            code,
            kernel_id=effective_kernel_id,
            allow_stdin=allow_stdin,
            envs=envs,
            **kwargs,
        ):
            yield chunk

    # ------------------------------------------------------------------
    # stop / reconnect / connectivity
    # ------------------------------------------------------------------

    async def stop(self) -> None:
        from e2b import AsyncSandbox

        if self._e2b_sandbox:
            logger.info(f"Killing E2B sandbox {self.external_id}...")
            await self._e2b_sandbox.kill()
            self._e2b_sandbox = None
            logger.info("E2B sandbox killed")
        elif self.external_id:
            logger.info(f"Killing E2B sandbox by ID: {self.external_id}...")
            await AsyncSandbox.kill(self.external_id, api_key=self.api_key)
            logger.info("E2B sandbox killed")

    async def _reconnect(self) -> None:
        from e2b import AsyncSandbox

        try:
            logger.info(f"Reconnecting to E2B sandbox {self.external_id}...")
            self._e2b_sandbox = await AsyncSandbox.connect(
                sandbox_id=self.external_id,
                api_key=self.api_key,
            )
            host = self._e2b_sandbox.get_host(JUPYTER_PORT)
            self.base_url = f"https://{host}"
            logger.info(f"Reconnected to E2B sandbox, base_url={self.base_url}")
        except Exception as e:
            logger.warning(
                f"Failed to reconnect to E2B sandbox {self.external_id}: {e}"
            )
            self._e2b_sandbox = None

    async def _ensure_e2b_sandbox_connected(self) -> None:
        if self._e2b_sandbox is None and self.external_id:
            await self._reconnect()
        if self._e2b_sandbox is None:
            raise RuntimeError("E2B sandbox is not connected")

    async def _is_e2b_sandbox_ready(self) -> bool:
        try:
            await self._ensure_e2b_sandbox_connected()
        except Exception:
            return False

        try:
            result = await self._e2b_sandbox.commands.run("true")
        except Exception:
            return False

        return getattr(result, "exit_code", 1) == 0

    async def is_up(self) -> bool:
        return await self._is_e2b_sandbox_ready()
