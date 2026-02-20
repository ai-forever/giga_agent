import mimetypes
import secrets
import time
import asyncio
import uuid
from collections.abc import AsyncIterator
from pathlib import PurePosixPath
from typing import Optional, Any

from pydantic import Field, PrivateAttr

from giga_agent.sandbox.base import (
    LARGE_FILE_THRESHOLD,
    ContentResult,
    FileReadResult,
    RedirectResult,
    StreamResult,
)
from giga_agent.sandbox.jupyter import JupyterSandbox
from giga_agent.sandbox.registry import SandboxRegistry
from giga_agent.core.logging import get_logger

logger = get_logger(__name__)

JUPYTER_PORT = 8888
S3_MOUNT_PREFIX = "/bucket/"
_S3_KEY_PREFIX = "giga_agent"
_S3_SUFFIX_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


@SandboxRegistry.register("e2b")
class E2BSandbox(JupyterSandbox):
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
    template: str = Field(default="jupyter-server", description="E2B sandbox template")
    idle_timeout: int = Field(
        default=300, description="Sandbox timeout in seconds (from provider)"
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
    _runtime_fields = JupyterSandbox._runtime_fields | {"jupyter_token"}

    # --- Private ---
    _e2b_sandbox: Any = PrivateAttr(default=None)

    def model_post_init(self, __context: Any) -> None:
        # Восстанавливаем _token из сохранённого jupyter_token (при восстановлении из БД)
        if self.jupyter_token:
            self._token = self.jupyter_token

    def get_connection_settings(self) -> dict:
        """Настройки для повторного подключения: external_id + jupyter_token."""
        return {
            "external_id": self.external_id,
            "jupyter_token": self._token,
        }

    @classmethod
    async def validate_settings(cls, settings: dict) -> dict:
        """
        Валидация settings для E2B провайдера с проверкой подключения.

        1. Схемная валидация (типы, обязательные поля).
        2. Проверка E2B API key — пробуем получить список sandbox'ов.
        3. Проверка S3 настроек и доступности бакета.
        """
        validated = await super().validate_settings(settings)

        # --- E2B API key ---
        api_key = validated.get("api_key", "")
        if not api_key or not api_key.strip():
            raise ValueError("api_key is required and must not be empty")

        await cls._check_e2b_api_key(api_key)

        # --- S3 settings (обязательные) ---
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
        """Проверяет валидность E2B API key через listing sandbox'ов."""
        from e2b import AsyncSandbox

        try:
            await AsyncSandbox.list(api_key=api_key).next_items()
        except Exception as e:
            raise ValueError(f"E2B API key validation failed: {e}") from e

    @staticmethod
    async def _check_s3_connection(settings: dict) -> None:
        """Проверяет доступность S3 бакета с указанными credentials."""
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

    async def up(self) -> None:
        """Создаёт E2B sandbox, монтирует S3, запускает Jupyter."""
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

        # Настраиваем S3 FUSE mount
        await self._mount_s3()

        # Запускаем Jupyter Server
        logger.info("Starting Jupyter Server...")
        await self._e2b_sandbox.commands.run(
            f"jupyter server --ip=0.0.0.0 --port={JUPYTER_PORT} > /dev/null 2>&1",
            background=True,
        )

        # Получаем публичный URL через model_post_init
        host = self._e2b_sandbox.get_host(JUPYTER_PORT)
        self.base_url = f"https://{host}"
        logger.info(f"Jupyter available at: {self.base_url}")

        # Ждём готовности Jupyter
        await self._wait_for_jupyter()

    async def _mount_s3(self) -> None:
        """Монтирует S3 бакет через s3fs FUSE."""
        logger.info(f"Mounting S3 bucket '{self.s3_bucket}'...")

        await self._e2b_sandbox.commands.run(
            f"mkdir -p {S3_MOUNT_PREFIX}",
            user="root",
        )
        # Важно: Jupyter/код обычно выполняется не под root, поэтому
        # mountpoint должен быть доступен для чтения/записи обычному пользователю.
        await self._e2b_sandbox.commands.run(
            f"chmod 0777 {S3_MOUNT_PREFIX}",
            user="root",
        )

        s3_cmd_parts = [
            f"s3fs {self.s3_bucket} {S3_MOUNT_PREFIX}",
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

    async def _wait_for_jupyter(self, timeout_seconds: int = 15) -> None:
        """Ждёт готовности Jupyter Server."""
        start_time = time.time()
        while True:
            if await self.is_up():
                logger.info("Jupyter is up and connected")
                return

            if time.time() - start_time > timeout_seconds:
                raise TimeoutError(
                    f"Jupyter did not start within {timeout_seconds} seconds"
                )
            logger.debug("Waiting for Jupyter...")
            await asyncio.sleep(1)

    async def upload_file(
        self,
        *,
        owner_id: uuid.UUID,
        file_name: str,
        content: bytes,
    ) -> str:
        """
        Загружает файл в S3 under giga_agent/{owner_id}/ с uniquify.

        Возвращает sandbox_path вида /bucket/{key}.
        """
        import aioboto3
        from botocore.exceptions import BotoCoreError, ClientError

        clean_name = file_name.strip()
        if not clean_name:
            raise ValueError("file_name must not be empty")

        key = await self._uniquify_s3_key(owner_id=owner_id, file_name=clean_name)

        content_type, _ = mimetypes.guess_type(clean_name)
        if not content_type:
            content_type = "application/octet-stream"
        if content_type.startswith("text/") and "charset" not in content_type:
            content_type += "; charset=utf-8"

        session = aioboto3.Session()
        last_error: Exception | None = None
        for _ in range(10):
            try:
                async with session.client(
                    "s3",
                    endpoint_url=self.s3_endpoint,
                    region_name=self.s3_region,
                    aws_access_key_id=self.aws_access_key_id,
                    aws_secret_access_key=self.aws_secret_access_key,
                ) as s3:
                    await s3.put_object(
                        Bucket=self.s3_bucket,
                        Key=key,
                        Body=content,
                        ContentType=content_type,
                        IfNoneMatch="*",
                    )
                    return f"{S3_MOUNT_PREFIX}{key}"
            except ClientError as e:
                code = (e.response.get("Error") or {}).get("Code")
                # Межпоточная гонка на имя: генерируем следующее имя и повторяем.
                if code in {"PreconditionFailed", "412"}:
                    key = await self._uniquify_s3_key(
                        owner_id=owner_id, file_name=clean_name
                    )
                    last_error = e
                    continue
                raise RuntimeError(f"S3 upload failed: {e}") from e
            except BotoCoreError as e:
                raise RuntimeError(f"S3 upload failed: {e}") from e

        raise RuntimeError(
            "Failed to upload file after retries due to concurrent name collisions"
        ) from last_error

    def requires_running_for_upload(self) -> bool:
        # Upload идёт напрямую в S3, поднятый E2B sandbox не нужен.
        return False

    async def read_file(self, sandbox_path: str) -> FileReadResult:
        """
        Читает файл и возвращает структурированный результат:
        - HTML на S3 → ContentResult / StreamResult (проксируем через backend)
        - Прочие S3 → RedirectResult (presigned URL)
        - Большие S3-объекты (>= 20 MB) → StreamResult
        - Локальные файлы → ContentResult
        """
        if self._is_s3_path(sandbox_path):
            key = self._s3_key_from_sandbox_path(sandbox_path)
            content_type, _ = mimetypes.guess_type(sandbox_path)
            media_type = content_type or "application/octet-stream"
            inline = sandbox_path.lower().endswith((".html", ".htm"))

            size = await self._get_s3_object_size(key)
            if size >= LARGE_FILE_THRESHOLD:
                return await self._stream_s3_object(
                    key, media_type=media_type, inline=inline, content_length=size,
                )
            if inline:
                data = await self._download_s3_object(key)
                return ContentResult(data=data, media_type=media_type, inline=True)
            url = await self._generate_presigned_url(key=key, expires_in=3600)
            return RedirectResult(url=url)

        await self._ensure_e2b_sandbox_connected()
        try:
            data = await self._e2b_sandbox.files.read(sandbox_path)
        except Exception as e:
            raise FileNotFoundError(f"Unable to read file '{sandbox_path}': {e}") from e

        if isinstance(data, bytes):
            raw = data
        elif isinstance(data, bytearray):
            raw = bytes(data)
        elif isinstance(data, str):
            raw = data.encode("utf-8")
        else:
            raw = str(data).encode("utf-8")

        return ContentResult(data=raw)

    def requires_running_for_read(self, sandbox_path: str) -> bool:
        # Для S3 paths читаем через presigned URL без поднятия sandbox.
        # Для внутренних путей нужен доступ к files.read в живом sandbox.
        return not self._is_s3_path(sandbox_path)

    def _is_s3_path(self, path: str) -> bool:
        return path.startswith(S3_MOUNT_PREFIX)

    def _s3_key_from_sandbox_path(self, path: str) -> str:
        if not self._is_s3_path(path):
            raise ValueError(f"Path '{path}' is not under S3 mount '{S3_MOUNT_PREFIX}'")

        key = path[len(S3_MOUNT_PREFIX) :].strip("/")
        if not key:
            raise ValueError(f"Path '{path}' does not contain a valid S3 object key")
        return key

    async def _get_s3_object_size(self, key: str) -> int:
        """Возвращает размер объекта в S3 (в байтах)."""
        import aioboto3
        from botocore.exceptions import BotoCoreError, ClientError

        session = aioboto3.Session()
        try:
            async with session.client(
                "s3",
                endpoint_url=self.s3_endpoint,
                region_name=self.s3_region,
                aws_access_key_id=self.aws_access_key_id,
                aws_secret_access_key=self.aws_secret_access_key,
            ) as s3:
                resp = await s3.head_object(Bucket=self.s3_bucket, Key=key)
                return int(resp["ContentLength"])
        except ClientError as e:
            code = (e.response.get("Error") or {}).get("Code")
            if code in {"NoSuchKey", "404"}:
                raise FileNotFoundError(f"S3 object not found: {key}") from e
            raise RuntimeError(f"Failed to get S3 object size for '{key}': {e}") from e
        except BotoCoreError as e:
            raise RuntimeError(f"Failed to get S3 object size for '{key}': {e}") from e

    async def _download_s3_object(self, key: str) -> bytes:
        """Скачивает объект из S3 целиком и возвращает содержимое."""
        import aioboto3
        from botocore.exceptions import BotoCoreError, ClientError

        session = aioboto3.Session()
        try:
            async with session.client(
                "s3",
                endpoint_url=self.s3_endpoint,
                region_name=self.s3_region,
                aws_access_key_id=self.aws_access_key_id,
                aws_secret_access_key=self.aws_secret_access_key,
            ) as s3:
                resp = await s3.get_object(Bucket=self.s3_bucket, Key=key)
                return await resp["Body"].read()
        except ClientError as e:
            code = (e.response.get("Error") or {}).get("Code")
            if code in {"NoSuchKey", "404"}:
                raise FileNotFoundError(f"S3 object not found: {key}") from e
            raise RuntimeError(f"Failed to download S3 object '{key}': {e}") from e
        except BotoCoreError as e:
            raise RuntimeError(f"Failed to download S3 object '{key}': {e}") from e

    async def _stream_s3_object(
        self,
        key: str,
        *,
        media_type: str = "application/octet-stream",
        inline: bool = False,
        content_length: int | None = None,
    ) -> StreamResult:
        """Создаёт StreamResult для потоковой отдачи S3-объекта."""
        import contextlib
        import aioboto3
        from botocore.exceptions import BotoCoreError, ClientError

        session = aioboto3.Session()
        stack = contextlib.AsyncExitStack()
        try:
            s3 = await stack.enter_async_context(
                session.client(
                    "s3",
                    endpoint_url=self.s3_endpoint,
                    region_name=self.s3_region,
                    aws_access_key_id=self.aws_access_key_id,
                    aws_secret_access_key=self.aws_secret_access_key,
                )
            )
            resp = await s3.get_object(Bucket=self.s3_bucket, Key=key)
        except ClientError as e:
            with contextlib.suppress(Exception):
                await stack.aclose()
            code = (e.response.get("Error") or {}).get("Code")
            if code in {"NoSuchKey", "404"}:
                raise FileNotFoundError(f"S3 object not found: {key}") from e
            raise RuntimeError(f"Failed to stream S3 object '{key}': {e}") from e
        except BotoCoreError as e:
            with contextlib.suppress(Exception):
                await stack.aclose()
            raise RuntimeError(f"Failed to stream S3 object '{key}': {e}") from e
        except Exception:
            with contextlib.suppress(Exception):
                await stack.aclose()
            raise

        async def _chunk_iter() -> AsyncIterator[bytes]:
            try:
                async for chunk in resp["Body"]:
                    yield chunk
            finally:
                with contextlib.suppress(Exception):
                    await stack.aclose()

        return StreamResult(
            stream=_chunk_iter(),
            media_type=media_type,
            inline=inline,
            content_length=content_length,
        )

    async def _generate_presigned_url(self, key: str, expires_in: int = 3600) -> str:
        import aioboto3
        from botocore.exceptions import BotoCoreError, ClientError

        session = aioboto3.Session()
        try:
            async with session.client(
                "s3",
                endpoint_url=self.s3_endpoint,
                region_name=self.s3_region,
                aws_access_key_id=self.aws_access_key_id,
                aws_secret_access_key=self.aws_secret_access_key,
            ) as s3:
                await s3.head_object(Bucket=self.s3_bucket, Key=key)
                return await s3.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self.s3_bucket, "Key": key},
                    ExpiresIn=expires_in,
                )
        except ClientError as e:
            code = (e.response.get("Error") or {}).get("Code")
            if code in {"NoSuchKey", "404"}:
                raise FileNotFoundError(f"S3 object not found: {key}") from e
            raise RuntimeError(f"Failed to generate S3 URL for '{key}': {e}") from e
        except BotoCoreError as e:
            raise RuntimeError(f"Failed to generate S3 URL for '{key}': {e}") from e

    async def _uniquify_s3_key(self, owner_id: uuid.UUID, file_name: str) -> str:
        clean = file_name.strip().replace("\\", "/").lstrip("/")
        path = PurePosixPath(clean)
        if path.name in {"", ".", ".."}:
            raise ValueError("file_name must contain a valid file name")
        if any(part in {".", ".."} for part in path.parts):
            raise ValueError("file_name must not contain '.' or '..' path segments")

        suffix_id = self._random_key_suffix()
        plotly_json_suffix = ".plotly.json"
        name = path.name
        if name.lower().endswith(plotly_json_suffix) and len(name) > len(plotly_json_suffix):
            suffix_start = len(name) - len(plotly_json_suffix)
            stem = name[:suffix_start]
            suffix = name[suffix_start:]
        else:
            stem = path.stem or path.name
            suffix = path.suffix
        candidate_name = (
            f"{stem}--{suffix_id}{suffix}" if suffix else f"{stem}--{suffix_id}"
        )

        parent = path.parent
        parent_parts = [] if str(parent) in {"", "."} else [p for p in parent.parts if p not in {"", "."}]

        key_parts = [_S3_KEY_PREFIX, str(owner_id), *parent_parts, candidate_name]
        return "/".join(key_parts)

    def _random_key_suffix(self) -> str:
        return "".join(secrets.choice(_S3_SUFFIX_ALPHABET) for _ in range(8))

    async def _ensure_e2b_sandbox_connected(self) -> None:
        if self._e2b_sandbox is None and self.external_id:
            await self._reconnect()
        if self._e2b_sandbox is None:
            raise RuntimeError("E2B sandbox is not connected")

    async def stop(self) -> None:
        """Останавливает (убивает) E2B sandbox."""
        from e2b import AsyncSandbox

        if self._e2b_sandbox:
            logger.info(f"Killing E2B sandbox {self.external_id}...")
            await self._e2b_sandbox.kill()
            self._e2b_sandbox = None
            logger.info("E2B sandbox killed")
        elif self.external_id:
            # Переподключение не нужно — можно убить по ID напрямую
            logger.info(f"Killing E2B sandbox by ID: {self.external_id}...")
            await AsyncSandbox.kill(self.external_id, api_key=self.api_key)
            logger.info("E2B sandbox killed")

    async def _reconnect(self) -> None:
        """
        Переподключается к существующему E2B sandbox по external_id
        и проставляет base_url.
        """
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

    async def is_up(self) -> bool:
        """
        Проверяет, доступен ли Jupyter в E2B sandbox.

        Если base_url ещё не установлен, но есть external_id —
        пытается восстановить подключение к существующему sandbox.
        """
        if not self.base_url and self.external_id:
            await self._reconnect()

        if not self.base_url:
            return False
        return await super().is_up()
