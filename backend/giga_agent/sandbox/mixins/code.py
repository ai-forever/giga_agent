from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Literal

from pydantic import BaseModel, Field


class ShellMeta(BaseModel):
    """Общая метаинформация shell-сессии, используемая всеми sandbox-реализациями."""

    shell_id: str
    command: str
    description: str | None = None
    cwd: str
    status: Literal["running", "completed", "failed"]
    started_at: str
    ended_at: str | None = None
    elapsed_ms: int | None = None
    exit_code: int | None = None
    pid: int | None = None
    output_path: str
    exit_code_path: str | None = None
    output_size_bytes: int = 0
    last_delivered_offset: int = 0
    last_update_at: str


class ShellRunResult(BaseModel):
    shell_id: str = Field(description="Уникальный идентификатор shell-сессии.")
    status: Literal["running", "completed", "failed"] = Field(
        description="Текущее состояние shell-команды."
    )
    backgrounded: bool = Field(
        description="Переведена ли команда в background к моменту возврата."
    )
    cwd: str = Field(description="Рабочая директория выполнения команды.")
    description: str | None = Field(
        default=None, description="Необязательное человекочитаемое описание задачи."
    )
    output: str = Field(description="Весь вывод, накопившийся за foreground-окно.")
    output_path: str = Field(description="Путь к полному output.log внутри sandbox.")
    pid: int | None = Field(default=None, description="PID процесса внутри sandbox.")
    exit_code: int | None = Field(
        default=None, description="Код завершения, если команда уже завершилась."
    )
    elapsed_ms: int | None = Field(
        default=None,
        description="Полное время выполнения в миллисекундах, если команда завершилась.",
    )
    await_hint: str | None = Field(
        default=None,
        description="Подсказка вызвать await_shell(shell_id=...), если команда еще идет.",
    )


class ShellAwaitResult(BaseModel):
    shell_id: str = Field(description="Идентификатор shell-сессии.")
    status: Literal["running", "completed", "failed", "not_found"] = Field(
        description="Текущее состояние shell-сессии."
    )
    output_delta: str = Field(
        description="Новый вывод, который еще не был доставлен агенту."
    )
    matched_pattern: bool = Field(
        description="Совпал ли pattern с накопленным выводом shell-сессии."
    )
    output_path: str | None = Field(
        default=None, description="Путь к полному output.log внутри sandbox."
    )
    exit_code: int | None = Field(
        default=None, description="Код завершения, если процесс уже завершился."
    )
    elapsed_ms: int | None = Field(
        default=None,
        description="Полное время выполнения в миллисекундах, если процесс завершился.",
    )
    read_full_log_hint: str = Field(
        description="Подсказка, как прочитать полный лог через output.log."
    )


class CodeMixin(ABC):
    """Миксин для окружений, поддерживающих выполнение кода."""

    @abstractmethod
    async def run_code(
        self,
        code: str,
        kernel_id: str | None = None,
        *,
        allow_stdin: bool = True,
        envs: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[dict[str, Any], str]:
        """
        Запускает выполнение кода.

        :param code: Исходный код для выполнения.
        :param kernel_id: Kernel ID.
        :param allow_stdin: Разрешить ли интерактивный stdin во время выполнения.
        :param envs: Дополнительные env-переменные для текущего выполнения.
        :param kwargs: Дополнительные параметры выполнения, поддерживаемые реализацией.
        :return: Асинхронный генератор, возвращающий результаты выполнения.
        """
        pass

    async def run_shell(
        self,
        command: str,
        *,
        working_directory: str | None = None,
        block_until_ms: int = 30000,
        description: str | None = None,
        envs: dict[str, str] | None = None,
    ) -> ShellRunResult:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement run_shell()"
        )

    async def await_shell(
        self,
        shell_id: str,
        *,
        block_until_ms: int = 30000,
        pattern: str | None = None,
    ) -> ShellAwaitResult:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement await_shell()"
        )
