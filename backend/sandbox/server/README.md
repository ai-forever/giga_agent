# SandboxAPI Server

In-guest agent, который живёт **внутри одной песочницы** (контейнер/VM образа
`mikelarg/code-interpreter`) и отдаёт унифицированный HTTP/WS API для выполнения
кода, shell-команд и работы с файлами. Аутентификация — один bearer-токен, с
которым запускается процесс.

Задача — заменить «болезненные» пути `local_docker` (чтение файлов через
`exec cat` целиком в память, base64-запись, `python -c` на каждую операцию,
O(n²) pattern-scan) на нативные потоковые реализации, и дать один API за которым
GigaAgent-сторона имеет **один тонкий провайдер** (`sandbox_api`).

## Запуск

```bash
SANDBOX_API_TOKEN=<secret> sandbox-server
# или
SANDBOX_API_TOKEN=<secret> python -m sandbox_server
```

### Переменные окружения

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `SANDBOX_API_TOKEN` | — (**обязательна**) | bearer-токен; без него сервер не стартует |
| `SANDBOX_API_HOST` | `0.0.0.0` | адрес прослушивания |
| `SANDBOX_API_PORT` | `49999` | порт |
| `SANDBOX_WORKDIR` | `/root` | дефолтный cwd для kernel'ов и shell |
| `SANDBOX_DEFAULT_KERNEL` | `python3` | kernelspec по умолчанию |
| `SANDBOX_KERNEL_STARTUP_TIMEOUT_SEC` | `60` | таймаут готовности kernel'а |
| `SANDBOX_MAX_KERNELS` | `0` | `>0` включает LRU-эвикцию kernel'ов |
| `SANDBOX_SHELL_SESSIONS_ROOT` | `/tmp/.sandbox_api/shell_sessions` | где хранятся логи shell |
| `SANDBOX_IDLE_TIMEOUT_SEC` | `0` | `>0` — self-shutdown по бездействию |
| `SANDBOX_REQUEST_LOG` | `true` | access-логи uvicorn |

## API

Все `/v1/*` требуют `Authorization: Bearer <token>` (WS — тем же заголовком или
`?token=`). `/healthz` и `/readyz` — без токена.

### System
- `GET /healthz` · `GET /readyz`
- `GET /v1/info` → версия, workdir, число активных kernel'ов/shell, uptime

### Kernels (нативно через jupyter_client)
- `POST /v1/kernels` `{kernel_name?, cwd?, env?}` → `{kernel_id, ...}`
- `GET /v1/kernels` → список (нужно для reconnect после рестарта backend'а)
- `POST /v1/kernels/{id}/interrupt` · `POST /v1/kernels/{id}/restart`
- `DELETE /v1/kernels/{id}`
- `WS /v1/kernels/{id}/execute` (или `{id}=new`) — стриминг:
  - client→server (1-е сообщение): `{"code","allow_stdin","envs","kernel_name?","cwd?"}`
  - server→client: `{"type":"kernel","kernel_id"}`, затем чанки:
    `{"type":"stdout"|"stderr","text"}`, `{"type":"result","data","execution_count"}`,
    `{"type":"display_data","data"}`, `{"type":"error","ename","evalue","traceback"}`,
    `{"type":"input_request","prompt","password"}`, `{"type":"done"}`, `{"type":"fatal","detail"}`
  - на `input_request` client отвечает `{"type":"input_reply","value"}`

Формат чанков совпадает с `giga_agent.sandbox.jupyter.run_code`, поэтому клиент
`SandboxAPISandbox.run_code` просто `json.loads` и `yield`.

### Shell (нативный реестр)
- `POST /v1/shell` `{command, working_directory?, block_until_ms?, description?, envs?}` → `ShellRunResult`
- `GET /v1/shell?only_running=` → список активных (нет в текущем контракте)
- `POST /v1/shell/{id}/await` `{block_until_ms?, pattern?}` → offset-дельта
- `POST /v1/shell/{id}/kill` → остановка по process-group (нет в текущем контракте)

### Skills (FS-backed, только для нативного провайдера `sandbox_api`)
> ⚠️ При переезде `local_docker`/`e2b` на это API их skill-операции сюда **НЕ**
> ходят: у них своя персистентность (локальная FS / S3). Эти ручки — про скиллы,
> хранящиеся прямо в файловой системе песочницы (`SANDBOX_SKILLS_ROOT`,
> по умолчанию `{workdir}/.skills`). Все ручки принимают опциональный `?owner_id=`
> для неймспейсинга.
- `GET /v1/skills` → runtime-листинг (скан манифестов SKILL.md) → `[{name, description, storage_path, sandbox_path}]`
- `PUT /v1/skills/{name}` — тело = **tar/tar.gz** архив файлов скилла; заменяет существующий; безопасная распаковка (`filter="data"`)
- `GET /v1/skills/{name}/files` → список относительных путей
- `GET /v1/skills/{name}/file?path=<relative>` → содержимое файла (text)
- `DELETE /v1/skills/{name}`

`sandbox_path` в ответах = абсолютная директория скилла в песочнице; клиентский
`get_skill_sandbox_path` = `{sandbox_path}/{relative}`.

### Files (стриминг + Range)
- `GET /v1/files?path=` — потоковое чтение, поддержка `Range` (206) → фикс OOM
- `PUT /v1/files?path=` — потоковая запись тела запроса на диск
- `HEAD /v1/files?path=` · `GET /v1/files/stat?path=`
- `DELETE /v1/files?path=[&recursive=]`
- `GET /v1/files/list?path=` · `POST /v1/files/mkdir?path=`

## Как это встроено в образ

Добавлено в `../Dockerfile` **аддитивно** (без смены CMD): пакет копируется в
`/root/.server/sandbox_server`, ставится через `uv pip`, доступен как
`sandbox-server`. Существующие рантаймы (`local_docker`, `e2b`) не затронуты и
поднимают Jupyter по-старому; переключение на этот сервер — отдельный шаг
(новый провайдер `sandbox_api` на GigaAgent-стороне).
```
