"""E2BSandbox — E2B Cloud-backed Jupyter sandbox runtime."""

import os
import secrets
import shlex
import uuid
from pathlib import Path
from typing import Any, Optional

from cashews import cache

from pydantic import Field, PrivateAttr

from giga_agent.conf import get_settings
from giga_agent.core.logging import get_logger
from giga_agent.sandbox.api_backed import APIBackedSandbox
from giga_agent.sandbox.e2b.constants import S3_MOUNT_PREFIX
from giga_agent.sandbox.e2b.files import S3FilesMixin
from giga_agent.sandbox.jupyter import JupyterSandbox
from giga_agent.sandbox.registry import SandboxRegistry

logger = get_logger(__name__)


@SandboxRegistry.register("e2b")
class E2BSandbox(APIBackedSandbox, S3FilesMixin, JupyterSandbox):
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

    # Наследуется от JupyterSandbox как required — здесь не используется
    # (кернелы/шелл/файлы идут через SandboxAPI), держим пустым.
    base_url: str = Field(default="", description="unused (legacy)")

    # Исключаем connection-поля из provider settings schema
    _runtime_fields = APIBackedSandbox._runtime_fields | {"owner_id"}

    # --- Private ---
    _e2b_sandbox: Any = PrivateAttr(default=None)
    _s3_prefix_ready: bool = PrivateAttr(default=False)

    def get_connection_settings(self) -> dict:
        settings: dict[str, Any] = {"external_id": self.external_id}
        if self.api_base_url:
            settings["api_base_url"] = self.api_base_url
        if self.api_token:
            settings["api_token"] = self.api_token
        return settings

    def current_workdir(self) -> str | None:
        return "/root"

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
        """Create E2B sandbox, mount S3, start the in-guest SandboxAPI server."""
        from e2b import AsyncSandbox

        settings = get_settings()
        api_port = settings.giga_agent_sandbox_api_port
        self.api_token = secrets.token_urlsafe(24)

        envs = {
            "MATPLOTLIBRC": "/root/.config/matplotlib/.matplotlibrc",
            "AWSACCESSKEYID": self.aws_access_key_id,
            "AWSSECRETACCESSKEY": self.aws_secret_access_key,
            "SANDBOX_API_TOKEN": self.api_token,
            "SANDBOX_API_PORT": str(api_port),
            "SANDBOX_WORKDIR": self.current_workdir() or "/root",
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

        await self._start_sandbox_api_server()
        self.api_base_url = f"https://{self._e2b_sandbox.get_host(api_port)}"
        await self._ensure_api_server_ready()
        logger.info(f"E2B SandboxAPI ready at: {self.api_base_url}")

    async def _start_sandbox_api_server(self) -> None:
        await self._ensure_e2b_sandbox_connected()
        logger.info("Starting SandboxAPI server in E2B sandbox...")
        # Логи в файл — читаемы через files-API (у e2b нет docker logs).
        await self._e2b_sandbox.commands.run(
            "sandbox-server-supervised > /tmp/sandbox-server.log 2>&1",
            background=True,
            user="root",
        )

    async def _ensure_api_server_ready(self) -> None:
        ok = await self._wait_for_sandbox_api(
            get_settings().giga_agent_sandbox_api_startup_timeout_sec
        )
        if not ok:
            raise RuntimeError(
                "SandboxAPI server did not become healthy in the e2b sandbox. "
                "Пересобери e2b-шаблон из образа с sandbox-server "
                f"(template={self.template})."
            )

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
            api_port = get_settings().giga_agent_sandbox_api_port
            self.api_base_url = f"https://{self._e2b_sandbox.get_host(api_port)}"
            # сервер мог не пережить простой — поднимем при необходимости
            if not await self._wait_for_sandbox_api(5):
                await self._start_sandbox_api_server()
                await self._ensure_api_server_ready()
            logger.info(f"Reconnected to E2B sandbox, api={self.api_base_url}")
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

    # ------------------------------------------------------------------
    # Skill file operations (S3-backed + cashews cache)
    # ------------------------------------------------------------------

    _SKILL_CACHE_TTL = int(os.getenv("GIGA_AGENT_SKILL_CACHE_TTL", "300"))
    _SKILL_CACHE_ENABLED = (
        os.getenv("GIGA_AGENT_SKILL_CACHE_ENABLED", "true").lower() != "false"
    )

    def _skill_s3_prefix(self, owner_id: uuid.UUID, skill_name: str) -> str:
        return f"skills/{owner_id}/{skill_name}"

    def _skill_cache_key(self, owner_id: uuid.UUID, skill_name: str, rel: str) -> str:
        return f"skill:file:{owner_id}:{skill_name}:{rel}"

    def _skill_list_cache_key(self, owner_id: uuid.UUID, skill_name: str) -> str:
        return f"skill:list:{owner_id}:{skill_name}"

    async def install_skill_files(
        self,
        owner_id: uuid.UUID,
        skill_name: str,
        source_dir: str | Path,
    ) -> str:
        import aioboto3

        source = Path(source_dir)
        if not source.is_dir():
            raise FileNotFoundError(f"Source directory not found: {source}")

        prefix = self._skill_s3_prefix(owner_id, skill_name)
        session = aioboto3.Session()

        async with session.client(
            "s3",
            endpoint_url=self.s3_endpoint,
            region_name=self.s3_region,
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_access_key,
        ) as s3:
            for file_path in source.rglob("*"):
                if not file_path.is_file():
                    continue
                rel = str(file_path.relative_to(source))
                key = f"{prefix}/{rel}"
                content = file_path.read_bytes()
                await s3.put_object(
                    Bucket=self.s3_bucket,
                    Key=key,
                    Body=content,
                )

        await self._invalidate_skill_cache(owner_id, skill_name)
        return f"skills/{skill_name}"

    async def read_skill_file(
        self, owner_id: uuid.UUID, storage_path: str, relative_path: str
    ) -> str:
        skill_name = storage_path.split("/")[-1]
        cache_key = self._skill_cache_key(owner_id, skill_name, relative_path)

        if self._SKILL_CACHE_ENABLED:
            cached = await cache.get(cache_key)
            if cached is not None:
                return cached

        prefix = self._skill_s3_prefix(owner_id, skill_name)
        key = f"{prefix}/{relative_path}"
        data = await self._download_s3_object(key)
        content = data.decode("utf-8")

        if self._SKILL_CACHE_ENABLED and self._SKILL_CACHE_TTL > 0:
            await cache.set(cache_key, content, expire=self._SKILL_CACHE_TTL)

        return content

    async def list_skill_files(
        self, owner_id: uuid.UUID, storage_path: str
    ) -> list[str]:
        import aioboto3

        skill_name = storage_path.split("/")[-1]
        cache_key = self._skill_list_cache_key(owner_id, skill_name)

        if self._SKILL_CACHE_ENABLED:
            cached = await cache.get(cache_key)
            if cached is not None:
                return cached

        prefix = self._skill_s3_prefix(owner_id, skill_name) + "/"
        result: list[str] = []
        session = aioboto3.Session()

        async with session.client(
            "s3",
            endpoint_url=self.s3_endpoint,
            region_name=self.s3_region,
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_access_key,
        ) as s3:
            paginator = s3.get_paginator("list_objects_v2")
            async for page in paginator.paginate(Bucket=self.s3_bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    rel = key[len(prefix) :]
                    if rel:
                        result.append(rel)

        result.sort()
        if self._SKILL_CACHE_ENABLED and self._SKILL_CACHE_TTL > 0:
            await cache.set(cache_key, result, expire=self._SKILL_CACHE_TTL)

        return result

    async def remove_skill_files(self, owner_id: uuid.UUID, storage_path: str) -> None:
        import aioboto3

        skill_name = storage_path.split("/")[-1]
        prefix = self._skill_s3_prefix(owner_id, skill_name) + "/"
        session = aioboto3.Session()

        async with session.client(
            "s3",
            endpoint_url=self.s3_endpoint,
            region_name=self.s3_region,
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_access_key,
        ) as s3:
            paginator = s3.get_paginator("list_objects_v2")
            async for page in paginator.paginate(Bucket=self.s3_bucket, Prefix=prefix):
                objects = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
                if objects:
                    await s3.delete_objects(
                        Bucket=self.s3_bucket,
                        Delete={"Objects": objects},
                    )

        await self._invalidate_skill_cache(owner_id, skill_name)

    def get_skill_sandbox_path(
        self, owner_id: uuid.UUID, storage_path: str, relative_path: str
    ) -> str:
        skill_name = storage_path.split("/")[-1]
        return f"{S3_MOUNT_PREFIX}.skills/{skill_name}/{relative_path}"

    async def _invalidate_skill_cache(
        self, owner_id: uuid.UUID, skill_name: str
    ) -> None:
        if not self._SKILL_CACHE_ENABLED:
            return
        pattern = f"skill:*:{owner_id}:{skill_name}*"
        try:
            await cache.delete_match(pattern)
        except Exception:
            pass
