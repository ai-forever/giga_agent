import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import ClassVar, Type

from pydantic import BaseModel, create_model
from typing_extensions import override

from langchain_core.load.serializable import Serializable


LARGE_FILE_THRESHOLD = 20 * 1024 * 1024  # 20 MB


@dataclass(frozen=True, slots=True)
class RedirectResult:
    """Route должен сделать HTTP redirect на этот URL."""

    url: str


@dataclass(frozen=True, slots=True)
class ContentResult:
    """Route должен отдать содержимое как StreamingResponse."""

    data: bytes
    media_type: str = "application/octet-stream"
    inline: bool = False


@dataclass(slots=True)
class StreamResult:
    """Route должен отдать содержимое потоково (для больших файлов)."""

    stream: AsyncIterator[bytes]
    media_type: str = "application/octet-stream"
    inline: bool = False
    content_length: int | None = None


FileReadResult = RedirectResult | ContentResult | StreamResult


class BaseSandbox(Serializable, ABC):
    """Абстрактный базовый класс для виртуальных окружений."""

    # Поля, управляемые системой (менеджером/БД), а НЕ пользовательскими settings.
    # Подклассы могут расширять через: _runtime_fields = BaseSandbox._runtime_fields | {"my_field"}
    _runtime_fields: ClassVar[set[str]] = {
        "base_url",  # устанавливается в up()
        "headers",  # внутренний для JupyterSandbox
        "idle_timeout",  # из SandboxProvider.idle_timeout (DB column)
        "external_id",  # из Sandbox.external_id (DB column)
    }

    @classmethod
    def settings_schema(cls) -> Type[BaseModel]:
        """
        Динамически генерирует Pydantic-модель для валидации provider_settings.

        Берёт все публичные поля runtime-класса и исключает _runtime_fields
        (поля, которые прокидываются системой, а не хранятся в settings JSON).
        """
        fields = {}
        for name, field_info in cls.model_fields.items():
            if name in cls._runtime_fields:
                continue
            # Сохраняем тип и default/description из оригинального FieldInfo
            fields[name] = (field_info.annotation, field_info)

        return create_model(f"{cls.__name__}Settings", **fields)

    @classmethod
    async def validate_settings(cls, settings: dict) -> dict:
        """
        Валидировать и нормализовать settings через settings_schema().

        Базовая реализация проверяет только схему (типы, обязательные поля).
        Подклассы могут расширить для проверки реального подключения.

        :param settings: Сырой dict настроек.
        :returns: Валидированный dict (без None-значений).
        :raises ValidationError: Если settings не проходят валидацию.
        :raises ValueError: Если проверка подключения не пройдена.
        """
        schema = cls.settings_schema()
        return schema(**settings).model_dump(exclude_none=True)

    @classmethod
    @override
    def is_lc_serializable(cls) -> bool:
        return True

    def get_connection_settings(self) -> dict:
        """
        Возвращает dict настроек, необходимых для повторного подключения
        к уже запущенному sandbox'у.

        Вызывается менеджером после up() и сохраняется в sandbox.settings в БД.
        При восстановлении runtime эти настройки прокидываются обратно
        через _merge_settings → конструктор.

        Подклассы должны переопределить, если им нужны данные для reconnect
        (например, external_id, токены и т.д.).
        """
        return {}

    @abstractmethod
    async def up(self) -> None:
        """Запускает виртуальное окружение."""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Останавливает виртуальное окружение."""
        pass

    @abstractmethod
    async def is_up(self) -> bool:
        """Проверяет, запущено ли окружение."""
        pass

    async def upload_file(
        self,
        *,
        owner_id: uuid.UUID,
        file_name: str,
        content: bytes,
    ) -> str:
        """
        Загрузить файл в хранилище sandbox и вернуть итоговый sandbox_path.

        Базовая реализация — заглушка. Подклассы переопределяют метод.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement upload_file()"
        )

    async def read_file(self, sandbox_path: str) -> FileReadResult:
        """
        Прочитать файл из sandbox_path.

        Возвращает один из вариантов FileReadResult:
        - RedirectResult — redirect на presigned URL
        - ContentResult — содержимое целиком (< 20 MB)
        - StreamResult — потоковая отдача (>= 20 MB)

        Базовая реализация — заглушка. Подклассы переопределяют метод.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement read_file()"
        )

    def requires_running_for_upload(self) -> bool:
        """
        Нужен ли поднятый sandbox для upload_file.

        По умолчанию считаем, что нужен. Провайдеры с прямой загрузкой во внешнее
        хранилище (например, S3) могут вернуть False.
        """
        return True

    def requires_running_for_read(self, sandbox_path: str) -> bool:
        """
        Нужен ли поднятый sandbox для read_file конкретного пути.

        По умолчанию считаем, что нужен. Провайдеры могут переопределить
        в зависимости от расположения файла.
        """
        return True
