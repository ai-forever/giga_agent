"""SandboxAPI Server — FastAPI application.

In-guest agent: живёт внутри одной песочницы, аутентифицирует запросы по одному
bearer-токену, и отдаёт унифицированный API: kernels (нативно через
jupyter_client), shell (нативный реестр), files (стриминг + Range).
"""

from __future__ import annotations

import asyncio
import platform
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect

from fastapi.responses import JSONResponse

from . import files as files_module
from .auth import authenticate_websocket, require_token
from .config import get_settings
from .kernels import KernelPool
from .logs import log_event, new_request_id, setup_logging
from .models import (
    CreateKernelRequest,
    InfoResponse,
    KernelInfo,
    KernelListResponse,
    ShellAwaitRequest,
    ShellAwaitResult,
    ShellKilledResponse,
    ShellListResponse,
    ShellRunRequest,
    ShellRunResult,
)
from .shell import ShellManager
from .skills import SkillsManager
from .skills import router as skills_router


def _server_version() -> str:
    for candidate in (Path(__file__).resolve().parent.parent / "VERSION",):
        try:
            return candidate.read_text(encoding="utf-8").strip()
        except OSError:
            continue
    return "0.0.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging()
    log_event("server_start", version=_server_version(), workdir=settings.workdir)
    app.state.settings = settings
    app.state.started_at = time.time()
    app.state.last_activity = time.time()
    app.state.kernel_pool = KernelPool(settings)
    app.state.shell_manager = ShellManager(settings)
    app.state.skills_manager = SkillsManager(settings)
    watchdog = asyncio.create_task(_idle_watchdog(app))
    try:
        yield
    finally:
        watchdog.cancel()
        await app.state.kernel_pool.shutdown_all()
        await app.state.shell_manager.shutdown_all()


async def _idle_watchdog(app: FastAPI) -> None:
    settings = app.state.settings
    if settings.idle_timeout_sec <= 0:
        return
    while True:
        await asyncio.sleep(min(30, settings.idle_timeout_sec))
        idle_for = time.time() - app.state.last_activity
        pool: KernelPool = app.state.kernel_pool
        shells: ShellManager = app.state.shell_manager
        busy = bool(pool.list()) or bool(shells.list(only_running=True))
        if idle_for >= settings.idle_timeout_sec and not busy:
            # мягкое самоубийство: SIGINT текущему процессу -> graceful shutdown
            import os
            import signal

            os.kill(os.getpid(), signal.SIGINT)
            return


app = FastAPI(title="SandboxAPI Server", version=_server_version(), lifespan=lifespan)


@app.middleware("http")
async def _touch_activity(request: Request, call_next):
    request.app.state.last_activity = time.time()
    rid = new_request_id()
    request.state.request_id = rid
    started = time.monotonic()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        # /healthz — шумный health-poll, его не логируем
        if request.url.path != "/healthz":
            log_event(
                "http",
                rid=rid,
                method=request.method,
                path=request.url.path,
                fpath=request.query_params.get("path"),
                status=status_code,
                ms=round((time.monotonic() - started) * 1000, 1),
            )


@app.exception_handler(Exception)
async def _unhandled_exc(request: Request, exc: Exception):
    import traceback

    log_event(
        "error",
        rid=getattr(request.state, "request_id", None),
        path=request.url.path,
        error=f"{type(exc).__name__}: {exc}",
        traceback=traceback.format_exc(),
    )
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


# --------------------------------------------------------------------------- #
# health / info
# --------------------------------------------------------------------------- #

system_router = APIRouter(tags=["system"])


@system_router.get("/healthz")
async def healthz():
    return {"status": "ok"}


@system_router.get("/readyz")
async def readyz(request: Request):
    ready = getattr(request.app.state, "kernel_pool", None) is not None
    if not ready:
        raise HTTPException(status_code=503, detail="not ready")
    return {"status": "ready"}


@system_router.get("/v1/info", response_model=InfoResponse, dependencies=[Depends(require_token)])
async def info(request: Request):
    st = request.app.state
    return InfoResponse(
        server_version=app.version,
        workdir=st.settings.workdir,
        skills_root=st.settings.skills_root,
        default_kernel=st.settings.default_kernel_name,
        platform=platform.platform(),
        python_version=platform.python_version(),
        uptime_sec=time.time() - st.started_at,
        active_kernels=len(st.kernel_pool.list()),
        active_shells=len(st.shell_manager.list(only_running=True)),
    )


# --------------------------------------------------------------------------- #
# kernels
# --------------------------------------------------------------------------- #

kernels_router = APIRouter(prefix="/v1/kernels", tags=["kernels"], dependencies=[Depends(require_token)])


def _kernel_info(entry) -> KernelInfo:
    return KernelInfo(
        kernel_id=entry.kernel_id,
        kernel_name=entry.kernel_name,
        cwd=entry.cwd,
        last_activity_at=entry.last_activity_at,
        execution_count=entry.execution_count,
    )


@kernels_router.post("", response_model=KernelInfo)
async def create_kernel(body: CreateKernelRequest, request: Request):
    pool: KernelPool = request.app.state.kernel_pool
    entry = await pool.create(kernel_name=body.kernel_name, cwd=body.cwd, env=body.env)
    return _kernel_info(entry)


@kernels_router.get("", response_model=KernelListResponse)
async def list_kernels(request: Request):
    pool: KernelPool = request.app.state.kernel_pool
    return KernelListResponse(kernels=[_kernel_info(e) for e in pool.list()])


@kernels_router.post("/{kernel_id}/interrupt")
async def interrupt_kernel(kernel_id: str, request: Request):
    ok = await request.app.state.kernel_pool.interrupt(kernel_id)
    if not ok:
        raise HTTPException(status_code=404, detail="kernel not found")
    return {"kernel_id": kernel_id, "interrupted": True}


@kernels_router.post("/{kernel_id}/restart")
async def restart_kernel(kernel_id: str, request: Request):
    ok = await request.app.state.kernel_pool.restart(kernel_id)
    if not ok:
        raise HTTPException(status_code=404, detail="kernel not found")
    return {"kernel_id": kernel_id, "restarted": True}


@kernels_router.delete("/{kernel_id}")
async def delete_kernel(kernel_id: str, request: Request):
    ok = await request.app.state.kernel_pool.delete(kernel_id)
    if not ok:
        raise HTTPException(status_code=404, detail="kernel not found")
    return {"kernel_id": kernel_id, "deleted": True}


@app.websocket("/v1/kernels/{kernel_id}/execute")
async def execute_ws(websocket: WebSocket, kernel_id: str):
    """Стриминг выполнения. ``kernel_id="new"`` создаёт свежий kernel.

    Клиент -> сервер (первое сообщение):
      {"code": str, "allow_stdin": bool, "envs": {...}, "kernel_name": str?, "cwd": str?}
    Сервер -> клиент: чанки run_code (см. models.py). На input_request клиент
    отвечает {"type": "input_reply", "value": str}.
    """
    if not await authenticate_websocket(websocket):
        return
    await websocket.accept()
    websocket.app.state.last_activity = time.time()
    pool: KernelPool = websocket.app.state.kernel_pool

    try:
        init = await websocket.receive_json()
    except (WebSocketDisconnect, ValueError):
        await websocket.close()
        return

    code = init.get("code", "")
    allow_stdin = bool(init.get("allow_stdin", True))
    envs = init.get("envs")

    started = time.monotonic()
    try:
        entry = await pool.get_or_create(
            None if kernel_id in ("new", "") else kernel_id,
            kernel_name=init.get("kernel_name"),
            cwd=init.get("cwd"),
            env=init.get("env"),
        )
    except Exception as exc:
        log_event("run_code", requested_kernel=kernel_id, status="kernel_start_failed", error=str(exc))
        await websocket.send_json({"type": "fatal", "detail": f"kernel start failed: {exc}"})
        await websocket.close()
        return

    await websocket.send_json({"type": "kernel", "kernel_id": entry.kernel_id})

    gen = pool.execute(entry, code, allow_stdin=allow_stdin, envs=envs)
    pending: str | None = None
    status = "ok"
    n_chunks = 0
    try:
        while True:
            try:
                chunk = await (gen.asend(pending) if pending is not None else anext(gen))
                pending = None
            except StopAsyncIteration:
                break
            n_chunks += 1
            if chunk.get("type") == "error":
                status = "error"
            await websocket.send_json(chunk)
            if chunk.get("type") == "input_request":
                reply = await websocket.receive_json()
                pending = str(reply.get("value", ""))
    except WebSocketDisconnect:
        await gen.aclose()
        log_event("run_code", kernel_id=entry.kernel_id, status="client_disconnect",
                  ms=round((time.monotonic() - started) * 1000, 1), chunks=n_chunks)
        return
    except Exception as exc:
        status = "fatal"
        try:
            await websocket.send_json({"type": "fatal", "detail": str(exc)})
        except Exception:
            pass
    finally:
        websocket.app.state.last_activity = time.time()
    log_event("run_code", kernel_id=entry.kernel_id, status=status,
              ms=round((time.monotonic() - started) * 1000, 1), chunks=n_chunks,
              code_len=len(code))
    await websocket.close()


# --------------------------------------------------------------------------- #
# shell
# --------------------------------------------------------------------------- #

shell_router = APIRouter(prefix="/v1/shell", tags=["shell"], dependencies=[Depends(require_token)])


@shell_router.post("", response_model=ShellRunResult)
async def run_shell(body: ShellRunRequest, request: Request):
    mgr: ShellManager = request.app.state.shell_manager
    try:
        return await mgr.run(
            body.command,
            working_directory=body.working_directory,
            block_until_ms=body.block_until_ms,
            description=body.description,
            envs=body.envs,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@shell_router.get("", response_model=ShellListResponse)
async def list_shells(request: Request, only_running: bool = False):
    mgr: ShellManager = request.app.state.shell_manager
    return ShellListResponse(shells=mgr.list(only_running=only_running))


@shell_router.post("/{shell_id}/await", response_model=ShellAwaitResult)
async def await_shell(shell_id: str, body: ShellAwaitRequest, request: Request):
    mgr: ShellManager = request.app.state.shell_manager
    try:
        return await mgr.await_shell(
            shell_id, block_until_ms=body.block_until_ms, pattern=body.pattern
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@shell_router.post("/{shell_id}/kill", response_model=ShellKilledResponse)
async def kill_shell(shell_id: str, request: Request):
    mgr: ShellManager = request.app.state.shell_manager
    killed, session = await mgr.kill(shell_id)
    if session is None:
        raise HTTPException(status_code=404, detail="shell not found")
    return ShellKilledResponse(shell_id=shell_id, status=session.status, killed=killed)


# --------------------------------------------------------------------------- #
# wiring
# --------------------------------------------------------------------------- #

app.include_router(system_router)
app.include_router(kernels_router)
app.include_router(shell_router)
app.include_router(files_module.router)
app.include_router(skills_router)
