"""Runtime configuration for the SandboxAPI Server.

Все настройки берутся из окружения — сервер запускается с токеном и парой
параметров, без внешних зависимостей (БД, Redis и т.п.). Это in-guest agent:
он живёт ВНУТРИ одной песочницы и управляет только своим процессом.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _str(name: str, default: str) -> str:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip()


@dataclass(frozen=True, slots=True)
class Settings:
    # --- auth ---
    token: str = ""
    # --- network ---
    host: str = "0.0.0.0"
    port: int = 49999
    # --- filesystem / execution ---
    workdir: str = "/root"
    # --- kernels ---
    default_kernel_name: str = "python3"
    kernel_startup_timeout_sec: int = 60
    max_kernels: int = 0  # 0 = без лимита; иначе LRU-эвикция
    # take-over: сколько ждать мягкого прерывания (SIGINT) текущего выполнения,
    # прежде чем жёстко рестартить процесс kernel'а под новый запрос
    preempt_timeout_sec: int = 5
    # --- shell ---
    shell_sessions_root: str = "/tmp/.sandbox_api/shell_sessions"
    # GC завершённых shell-сессий (память + логи в /tmp растут иначе бесконечно)
    shell_session_ttl_sec: int = 3600
    max_completed_shell_sessions: int = 200
    # runaway-вывод: если лог команды перерастает лимит — команда убивается,
    # а лог усекается до головы (0 = без лимита). Поллинг, не жёсткая граница:
    # между опросами лог может немного перерасти лимит.
    max_log_bytes: int = 256 * 1024 * 1024
    # --- skills (FS-backed; только для нативного провайдера sandbox_api) ---
    skills_root: str = "/root/.skills"
    # верхний предел разовой отдачи вывода shell/файла в память (для не-stream веток)
    max_inline_read_bytes: int = 20 * 1024 * 1024  # 20 MB
    # --- lifecycle ---
    idle_timeout_sec: int = 0  # 0 = не выключаться; иначе self-shutdown по бездействию
    # --- misc ---
    request_log: bool = True

    stream_chunk_size: int = field(default=1024 * 1024, init=False)

    @property
    def kernel_lru_enabled(self) -> bool:
        return self.max_kernels > 0


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    token = _str("SANDBOX_API_TOKEN", "")
    if not token:
        raise RuntimeError(
            "SANDBOX_API_TOKEN is required: the server refuses to start without a "
            "bearer token to authenticate requests."
        )
    workdir = _str("SANDBOX_WORKDIR", "/root")
    return Settings(
        token=token,
        host=_str("SANDBOX_API_HOST", "0.0.0.0"),
        port=_int("SANDBOX_API_PORT", 49999),
        workdir=workdir,
        skills_root=_str("SANDBOX_SKILLS_ROOT", f"{workdir.rstrip('/')}/.skills"),
        default_kernel_name=_str("SANDBOX_DEFAULT_KERNEL", "python3"),
        kernel_startup_timeout_sec=_int("SANDBOX_KERNEL_STARTUP_TIMEOUT_SEC", 60),
        max_kernels=_int("SANDBOX_MAX_KERNELS", 0),
        preempt_timeout_sec=_int("SANDBOX_PREEMPT_TIMEOUT_SEC", 5),
        shell_sessions_root=_str(
            "SANDBOX_SHELL_SESSIONS_ROOT", "/tmp/.sandbox_api/shell_sessions"
        ),
        shell_session_ttl_sec=_int("SANDBOX_SHELL_SESSION_TTL_SEC", 3600),
        max_completed_shell_sessions=_int(
            "SANDBOX_MAX_COMPLETED_SHELL_SESSIONS", 200
        ),
        max_log_bytes=_int("SANDBOX_MAX_LOG_BYTES", 256 * 1024 * 1024),
        max_inline_read_bytes=_int("SANDBOX_MAX_INLINE_READ_BYTES", 20 * 1024 * 1024),
        idle_timeout_sec=_int("SANDBOX_IDLE_TIMEOUT_SEC", 0),
        request_log=_str("SANDBOX_REQUEST_LOG", "true").lower() != "false",
    )
