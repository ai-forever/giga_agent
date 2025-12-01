import os
import time
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.run_jupyter import StatefulKernel
from app.settings import settings

app = FastAPI()

origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # кому разрешаем
    allow_credentials=True,  # передавать ли куки/креденшалы
    allow_methods=["*"],  # какие HTTP-методы
    allow_headers=["*"],  # какие заголовки
)

app.kernels = {}
app.kernels_last_request = {}

STATE_DIR = settings.state_dir
os.makedirs(STATE_DIR, exist_ok=True)

MAX_IDLE = settings.max_kernel_live


class CodeRequest(BaseModel):
    kernel_id: str
    script: str


async def load_wrapper(kernel_id: str):
    state_file = os.path.join(STATE_DIR, f"{kernel_id}.pkl")
    wrapper = StatefulKernel(state_file=state_file, idle_timeout=MAX_IDLE)
    # Запускаем ядро и (опционально) сразу загружаем предыдущий state
    await wrapper.start()
    return wrapper


@app.post("/code")
async def code(request: CodeRequest):
    wrapper = app.kernels.get(request.kernel_id)
    if wrapper is None:
        wrapper = await load_wrapper(request.kernel_id)
        app.kernels[request.kernel_id] = wrapper
    result, err, _, attachments = await wrapper.execute(request.script)
    app.kernels_last_request[request.kernel_id] = time.time()
    return {
        "result": result,
        "is_exception": bool(err),
        "exception": err,
        "attachments": attachments,
    }


@app.post("/start")
async def start_kernel():
    kernel_id = str(uuid.uuid4())
    wrapper = await load_wrapper(kernel_id)
    app.kernels[kernel_id] = wrapper
    app.kernels_last_request[kernel_id] = time.time()
    print("Started kernel {}".format(kernel_id))
    return {"id": kernel_id}


class KernelRequest(BaseModel):
    kernel_id: str


@app.post("/shutdown")
async def shutdown_kernel(request: KernelRequest):
    wrapper = app.kernels.get(request.kernel_id)
    if wrapper is None:
        raise HTTPException(status_code=404, detail="Kernel not found")
    # Сохраняем и убиваем
    await wrapper.shutdown()
    return {"completed": True}
