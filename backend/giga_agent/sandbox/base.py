import enum
import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Type

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, create_model

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

    from giga_agent.core.agent.base import BaseAgent
    from giga_agent.core.agent.types import AgentState
    from giga_agent.models.users import UserShort
    from giga_agent.models.sandbox import SandboxProviderSnapshot, SandboxSnapshot
    from giga_agent.sandbox.manager.types import OrphanAction


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


class RuntimeReconcileOutcome(enum.Enum):
    """Итог сверки желаемых настроек рантайма с реально запущенным ресурсом."""

    NOOP = "noop"  # активный ресурс уже соответствует настройкам
    HOT_UPDATED = "hot_updated"  # горячие поля применены на лету, без рестарта
    RECREATE = "recreate"  # изменились холодные поля — нужен пересоздать ресурс


@dataclass(frozen=True, slots=True)
class RuntimeSkillInfo:
    """Skill metadata discovered directly from a sandbox runtime."""

    name: str
    description: str = ""
    storage_path: str | None = None
    source_url: str | None = None


class BaseSandbox(BaseModel, ABC):
    """Абстрактный базовый класс для виртуальных окружений."""

    max_active_sandboxes: int | None = None
    sandbox_id: uuid.UUID | None = None
    provider_id: uuid.UUID | None = None

    # Поля, управляемые системой (менеджером/БД), а НЕ пользовательскими settings.
    # Подклассы могут расширять через: _runtime_fields = BaseSandbox._runtime_fields | {"my_field"}
    _runtime_fields: ClassVar[set[str]] = {
        "base_url",  # устанавливается в up()
        "headers",  # внутренний для JupyterSandbox
        "idle_timeout",  # из SandboxProvider.idle_timeout (DB column)
        "external_id",  # из Sandbox.external_id (DB column)
        "sandbox_id",  # из Sandbox.id (DB column)
        "provider_id",  # из Sandbox.provider_id (DB column)
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
            if name == "max_active_sandboxes" and not cls.has_limit_cls():
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
    def has_limit_cls(cls) -> bool:
        return False

    def has_limit(self) -> bool:
        return self.has_limit_cls()

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

    def preserve_runtime_state_on_stop(self) -> bool:
        """Если True, менеджер НЕ затирает external_id и connection settings
        в БД при stop(). Используется рантаймами, которые держат тот же
        внешний ресурс между stop/up (например, LocalDocker с not_remove)."""
        return False

    async def reconcile_runtime_settings(self) -> "RuntimeReconcileOutcome":
        """Свести желаемые настройки (поля этого объекта, собранные из свежих
        provider/sandbox settings) с реально запущенным ресурсом.

        Вызывается менеджером в ensure_running_for_user для уже поднятого
        рантайма. Базовая реализация ничего не делает — провайдеры, у которых
        настройки вшиты в ресурс при создании (например, LocalDocker), должны
        переопределить метод: горячие поля применить на лету и вернуть
        HOT_UPDATED, при изменении холодных полей вернуть RECREATE.
        """
        return RuntimeReconcileOutcome.NOOP

    def get_prompt(
        self,
        user: "UserShort | None" = None,
        agent: "BaseAgent | None" = None,
        state: "AgentState | None" = None,
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> str:
        """Вернуть дополнительные инструкции о среде выполнения для агента."""
        _ = user, agent, state, config, kwargs
        return ""

    def current_workdir(self) -> str | None:
        """Текущая рабочая директория рантайма в виде абсолютного пути.

        Используется, например, для подсказок в сообщениях об ошибках.
        Подклассы переопределяют, если умеют возвращать осмысленный cwd.
        """
        return None

    @staticmethod
    def get_tools() -> list["BaseTool"]:
        """Вернуть sandbox-специфичные инструменты. Подклассы переопределяют."""
        return []

    @classmethod
    async def cleanup_orphans(
        cls,
        *,
        providers: list["SandboxProviderSnapshot"],
        sandboxes: list["SandboxSnapshot"],
    ) -> list["OrphanAction"]:
        return []

    @classmethod
    async def stop_external_runtime(cls, external_id: str) -> None:
        raise NotImplementedError(
            f"{cls.__name__} does not implement stop_external_runtime()"
        )

    @classmethod
    async def remove_external_runtime(cls, external_id: str) -> None:
        await cls.stop_external_runtime(external_id)

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

    async def delete_file(self, sandbox_path: str) -> None:
        """
        Удалить файл по sandbox_path в backing-хранилище провайдера.

        Базовая реализация — заглушка. Подклассы переопределяют метод.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement delete_file()"
        )

    async def write_file_content(self, sandbox_path: str, content: bytes) -> None:
        """
        Записать байты в файл по произвольному пути внутри sandbox.

        Создаёт родительские директории при необходимости.
        Перезаписывает файл, если он уже существует (create-only guard — на уровне тула).

        Базовая реализация — заглушка. Подклассы переопределяют метод.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement write_file_content()"
        )

    async def file_exists(self, sandbox_path: str) -> bool:
        """
        Проверить, существует ли файл по указанному sandbox_path.

        Базовая реализация — заглушка. Подклассы переопределяют метод.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement file_exists()"
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

    def requires_running_for_delete(self, sandbox_path: str) -> bool:
        """
        Нужен ли поднятый sandbox для delete_file конкретного пути.

        По умолчанию считаем, что нужен. Провайдеры с прямым доступом к внешнему
        хранилищу (например, S3) могут вернуть False.
        """
        return True

    def requires_running_for_write(self, sandbox_path: str) -> bool:
        """
        Нужен ли поднятый sandbox для write_file_content конкретного пути.

        По умолчанию считаем, что нужен. Провайдеры с прямым доступом к
        хранилищу могут вернуть False.
        """
        return True

    def requires_running_for_file_exists(self, sandbox_path: str) -> bool:
        """
        Нужен ли поднятый sandbox для file_exists конкретного пути.

        По умолчанию считаем, что нужен. Провайдеры с прямым доступом к
        хранилищу могут вернуть False.
        """
        return True

    # ---- Runtime skill discovery ----

    def supports_runtime_skill_listing(self) -> bool:
        """
        Может ли sandbox быть источником правды для списка доступных skills.
        """
        return False

    async def list_skills(self, owner_id: uuid.UUID) -> list[RuntimeSkillInfo]:
        """
        Вернуть skills, обнаруженные напрямую в runtime.

        Базовая реализация пустая: сервис вызывает этот метод только если
        supports_runtime_skill_listing() возвращает True.
        """
        _ = owner_id
        return []

    # ---- Skill file operations ----

    async def install_skill_files(
        self,
        owner_id: uuid.UUID,
        skill_name: str,
        source_dir: str | Path,
    ) -> str:
        """
        Install skill files into the sandbox storage.

        Returns the storage_path that uniquely identifies this skill's files.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement install_skill_files()"
        )

    async def read_skill_file(
        self, owner_id: uuid.UUID, storage_path: str, relative_path: str
    ) -> str:
        """Read a skill file (SKILL.md, scripts/*, references/*)."""
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement read_skill_file()"
        )

    async def list_skill_files(
        self, owner_id: uuid.UUID, storage_path: str
    ) -> list[str]:
        """List all files of a skill by storage_path. Returns relative paths."""
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement list_skill_files()"
        )

    async def remove_skill_files(self, owner_id: uuid.UUID, storage_path: str) -> None:
        """Remove all skill files from sandbox storage."""
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement remove_skill_files()"
        )

    def get_skill_sandbox_path(
        self, owner_id: uuid.UUID, storage_path: str, relative_path: str
    ) -> str:
        """
        Return the sandbox-visible path for a skill file, so the agent can
        pass it to read_file / cat / python tools.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement get_skill_sandbox_path()"
        )
