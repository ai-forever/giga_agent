import asyncio
import json
import logging
import os
import re
import time

import jupyter_client

logger = logging.getLogger(__name__)

ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


class KernelDeath(Exception):
    pass


async def async_run_code(
    km: jupyter_client.AsyncKernelManager,
    code,
    *,
    interrupt_after=30,
    iopub_timeout=40,
    wait_for_ready_timeout=30,
    shutdown_kernel=False,
):
    assert iopub_timeout > interrupt_after
    try:

        async def get_iopub_msg_with_death_detection(
            kc: jupyter_client.AsyncKernelClient, *, timeout=None
        ):
            loop = asyncio.get_running_loop()
            dead_fut = loop.create_future()

            def restarting():
                assert False, (
                    "Restart shouldn't happen because "
                    "config.KernelRestarter.restart_limit is expected to be set to 0"
                )

            def dead():
                logger.info("Kernel has died, will NOT restart")
                dead_fut.set_result(None)

            msg_task = asyncio.create_task(kc.get_iopub_msg(timeout=timeout))
            km.add_restart_callback(restarting, "restart")
            km.add_restart_callback(dead, "dead")
            try:
                done, _ = await asyncio.wait(
                    [dead_fut, msg_task], return_when=asyncio.FIRST_COMPLETED
                )
                if dead_fut in done:
                    raise KernelDeath()
                assert msg_task in done
                return await msg_task
            finally:
                msg_task.cancel()
                km.remove_restart_callback(restarting, "restart")
                km.remove_restart_callback(dead, "dead")

        async def send_interrupt():
            await asyncio.sleep(interrupt_after)
            await km.interrupt_kernel()

        async def monitor_stdin_for_input_request(
            kc: jupyter_client.AsyncKernelClient, input_needed_event: asyncio.Event
        ):
            """
            Фоново слушает stdin-канал ядра и выставляет флаг, если ядро
            запрашивает ввод пользователя (msg_type == 'input_request').
            Не блокирует основной цикл чтения IOPub, так как работает в отдельном таске.
            """
            try:
                while True:
                    msg = await kc.get_stdin_msg()
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "STDIN MESSAGE: %s", json.dumps(msg, indent=2, default=str)
                        )
                    # Сообщение может иметь msg_type в корне или в header
                    msg_type = msg.get("msg_type") or msg.get("header", {}).get(
                        "msg_type"
                    )
                    if msg_type == "input_request":
                        input_needed_event.set()
                        return
            except Exception:
                # Любые ошибки stdin-листенера не должны валить выполнение
                logger.debug("STDIN listener stopped", exc_info=True)

        async def run():
            kc = km.client()
            kc.start_channels()
            await kc.wait_for_ready(timeout=wait_for_ready_timeout)
            msg_id = kc.execute(code)
            execute_result = {}
            error_traceback = None
            stream_text_list = []
            attachments = []
            input_needed_event = asyncio.Event()
            stdin_listener_task = asyncio.create_task(
                monitor_stdin_for_input_request(kc, input_needed_event)
            )
            input_note_added = False
            while True:
                # Параллельно ждём либо новое IOPub сообщение,
                # либо сигнал о требуемом вводе
                msg_task = asyncio.create_task(
                    get_iopub_msg_with_death_detection(kc, timeout=iopub_timeout)
                )
                input_task = asyncio.create_task(input_needed_event.wait())
                done, pending = await asyncio.wait(
                    [msg_task, input_task], return_when=asyncio.FIRST_COMPLETED
                )
                if input_task in done and not input_note_added:
                    # Быстро реагируем на запрос ввода
                    error_traceback = (
                        "Exception: Execute commands/code "
                        "without interacting with user!\n"
                    )
                    input_note_added = True
                    msg_task.cancel()
                    break
                # Иначе пришло IOPub сообщение
                input_task.cancel()
                message = await msg_task
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(json.dumps(message, indent=2, default=str))
                assert message["parent_header"]["msg_id"] == msg_id
                msg_type = message["msg_type"]
                if msg_type == "status":
                    if message["content"]["execution_state"] == "idle":
                        break
                elif msg_type == "stream":
                    stream_text = message["content"]["text"]
                    stream_text_list.append(stream_text)
                elif msg_type == "execute_result":
                    execute_result = message["content"]["data"]
                elif msg_type == "error":
                    error_traceback_lines = message["content"]["traceback"]
                    error_traceback = "\n".join(error_traceback_lines)
                    error_traceback = ansi_escape.sub("", error_traceback)
                elif msg_type == "execute_input":
                    pass
                elif msg_type == "display_data":
                    attachments.append(message["content"]["data"])
                else:
                    assert False, f"Unknown message_type: {msg_type}"

            try:
                stdin_listener_task.cancel()
            finally:
                kc.stop_channels()

            return (
                "".join(stream_text_list) + execute_result.get("text/plain", ""),
                error_traceback,
                "".join(stream_text_list),
                attachments,
            )

        if interrupt_after:
            run_task = asyncio.create_task(run())
            send_interrupt_task = asyncio.create_task(send_interrupt())
            done, _ = await asyncio.wait(
                [run_task, send_interrupt_task], return_when=asyncio.FIRST_COMPLETED
            )
            if run_task in done:
                send_interrupt_task.cancel()
            else:
                assert send_interrupt_task in done
            result = await run_task
        else:
            result = await run()
        return result

    finally:
        if shutdown_kernel:
            await km.shutdown_kernel()


class StatefulKernel:
    """
    Обёртка над AsyncKernelManager, которая:
    - при старте — запускает ядро и загружает состояние из файла (если есть)
    - при каждом execute — обновляет метку last_used
    - фоновым таском следит за простоями и по таймауту:
        * сохраняет состояние в файл
        * завершает ядро
    """

    def __init__(
        self,
        kernel_name: str = "python3",
        state_file: str = "kernel_state.pkl",
        idle_timeout: float = 300.0,  # seconds
    ):
        self.kernel_name = kernel_name
        self.state_file = state_file
        self.idle_timeout = idle_timeout
        print(state_file)

        self.km: jupyter_client.AsyncKernelManager | None = None
        self.last_used: float | None = None
        self._idle_task: asyncio.Task | None = None

    def _rewrite_pip_commands(self, code: str) -> tuple[str, bool]:
        """
        Переписывает строки вида:
          - `!pip ...` или `!pip3 ...`
          - `!python -m pip ...` или `!python3 -m pip ...`
          - (на старте строки) `pip ...` или `pip3 ...`
        в  вариант, привязанный к интерпретатору ядра:
          - `!uv pip ...`

        Возвращает (новый_код, содержит_ли_pip-команды).
        """
        lines = code.splitlines()
        new_lines: list[str] = []
        contains_pip = False

        for line in lines:
            stripped = line.lstrip()
            leading_ws = line[: len(line) - len(stripped)]

            # Переписывание bang-команд
            if stripped.startswith("!"):
                bang_body = stripped[1:]
                # случаи: pip / pip3
                if re.match(r"^(pip3?)(\b|\s)", bang_body):
                    contains_pip = True
                    rest = re.sub(r"^(pip3?)(\b|\s)", "", bang_body, count=1)
                    new_lines.append(f"{leading_ws}!uv pip{rest}")
                    continue
                # случаи: python -m pip / python3 -m pip
                if re.match(r"^python(3)?\s+-m\s+pip(\b|\s)", bang_body):
                    contains_pip = True
                    rest = re.sub(
                        r"^python(3)?\s+-m\s+pip(\b|\s)", "", bang_body, count=1
                    )
                    new_lines.append(f"{leading_ws}!uv pip{rest}")
                    continue

                new_lines.append(line)
                continue

            # На старте строки встречается голый `pip ...` — превратим в bang-команду
            if re.match(r"^\s*pip3?\b", line):
                contains_pip = True
                rest = re.sub(r"^\s*pip3?\b", "", line, count=1)
                new_lines.append(f"{leading_ws}!uv pip{rest}")
                continue

            new_lines.append(line)

        return "\n".join(new_lines), contains_pip

    async def start(self):
        if self.km is None:
            # 1) Запускаем новое ядро
            self.km = jupyter_client.AsyncKernelManager(kernel_name=self.kernel_name)
            await self.km.start_kernel()

            # 2) Сразу после старта — если есть файл состояния, загружаем его
            if os.path.exists(self.state_file):
                load_code = f"import dill; dill.load_session('{self.state_file}')"
                await async_run_code(self.km, load_code)

        # Запускаем watcher простоя, если ещё не запущен
        if self._idle_task is None:
            self._idle_task = asyncio.create_task(self._idle_watcher())

    async def execute(self, code: str):
        # Убедиться, что ядро запущено и состояние загружено
        await self.start()
        # Обновить метку активности
        self.last_used = time.time()
        # Переписать потенциально небезопасные команды
        # установки pip в привязанные к ядру
        rewritten_code, contains_pip = self._rewrite_pip_commands(code)

        # Для pip-установок отключаем авто-интеррапт и увеличиваем таймауты
        if contains_pip:
            result = await async_run_code(
                self.km,
                rewritten_code,
                iopub_timeout=600,
                wait_for_ready_timeout=60,
                shutdown_kernel=False,
            )
        else:
            # Выполнить код через async_run_code с настройками по умолчанию
            result = await async_run_code(
                self.km, rewritten_code, shutdown_kernel=False
            )
        return result

    async def shutdown(self):
        """Сохранить состояние и остановить ядро."""
        if self.km is not None:
            # Попытаться сохранить состояние
            try:
                load_code = f"import dill; dill.dump_session('{self.state_file}')"
                await async_run_code(self.km, load_code)
            except Exception:
                logger.exception("Не удалось сохранить состояние ядра")

            # Останавливаем само ядро
            await self.km.shutdown_kernel(now=True)

        # Сбросить всё, чтобы при следующем start() поднялось заново
        self.km = None
        self.last_used = None
        if self._idle_task:
            self._idle_task.cancel()
            self._idle_task = None

    async def _idle_watcher(self):
        while True:
            print(self.idle_timeout)
            await asyncio.sleep(self.idle_timeout / 2)
            if self.last_used and (time.time() - self.last_used > self.idle_timeout):
                print(
                    f"Ядро не использовалось {self.idle_timeout}s, сохраняем и убиваем"
                )
                await self.shutdown()
                break
