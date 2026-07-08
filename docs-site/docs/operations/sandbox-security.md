---
title: "Изолированная среда и безопасность"
description: "Границы доверия для выполнения кода, команд и работы с файлами."
---

# Изолированная среда и безопасность

GigaAgent может выполнять код и команды через изолированные среды. Это мощная возможность, поэтому её нужно настраивать как границу доверия, а не как обычную функцию интерфейса.

Термин `sandbox` в интерфейсе и коде означает изолированную среду выполнения.

## Поддерживаемые варианты

В текущей ветке `main` есть реализации для:

- локального Docker;
- локального Jupyter;
- E2B;
- общего слоя управления средами, файлами и жизненным циклом.

Модуль REPL может добавлять инструменты `python`, `shell`, `await_shell`, а провайдеры изолированной среды могут добавлять дополнительные инструменты, например `open_port`.

## Локальный Docker

Основные значения по умолчанию:

| Переменная | Значение |
|---|---:|
| `GIGA_AGENT_LOCAL_SANDBOX_ENABLED` | `true` |
| `GIGA_AGENT_LOCAL_DOCKER_IMAGE` | `mikelarg/code-interpreter:0.0.5` |
| `GIGA_AGENT_LOCAL_DOCKER_MEMORY_LIMIT_MB` | `2048` |
| `GIGA_AGENT_LOCAL_DOCKER_MEMORY_RESERVATION_MB` | `512` |
| `GIGA_AGENT_LOCAL_DOCKER_VCPU` | `1.0` |
| `GIGA_AGENT_LOCAL_DOCKER_PIDS_LIMIT` | `256` |
| `GIGA_AGENT_LOCAL_DOCKER_SHM_SIZE_MB` | `128` |
| `GIGA_AGENT_LOCAL_DOCKER_MAX_ACTIVE_SANDBOXES` | `3` |
| `GIGA_AGENT_LOCAL_DOCKER_READONLY_ROOTFS` | `false` |

Доступ к Docker-сокету следует считать повышенным уровнем доверия: он может дать пользователю существенное влияние на машину, где запущен сервер.

## Локальный Jupyter

Основные значения по умолчанию:

| Переменная | Значение |
|---|---:|
| `GIGA_AGENT_LOCAL_JUPYTER_STARTUP_TIMEOUT_SEC` | `20` |
| `GIGA_AGENT_LOCAL_JUPYTER_GRACEFUL_SHUTDOWN_TIMEOUT_SEC` | `5` |
| `GIGA_AGENT_LOCAL_JUPYTER_WORKING_DIR` | пусто |
| `GIGA_AGENT_LOCAL_JUPYTER_FILES_PATH` | пусто |
| `GIGA_AGENT_LOCAL_JUPYTER_RUNTIME_DIR` | пусто |
| `GIGA_AGENT_LOCAL_JUPYTER_PYTHON_EXECUTABLE` | пусто |
| `GIGA_AGENT_LOCAL_JUPYTER_SECURE_EXEC_DEFAULT` | `false` |
| `GIGA_AGENT_LOCAL_JUPYTER_SECURE_EXEC_BACKEND` | `auto` |
| `GIGA_AGENT_LOCAL_JUPYTER_NETWORK_MODE` | `host` |

Jupyter-среда устанавливается через дополнительный набор зависимостей `backend[jupyter]` при работе из репозитория.

## Очистка сред

Сервер запускает фоновые задачи очистки, если они включены:

- очистка простаивающих сред: интервал `60s`;
- очистка осиротевших сред: интервал `120s`;
- время жизни запускающейся среды: `120s`.

Очистка помогает освобождать ресурсы, но не заменяет ограничения прав, памяти, процессов и доступных каталогов.

## Практический список проверок

- Включайте выполнение кода только тем пользователям, которым оно действительно нужно.
- Не открывайте изолированной среде доступ к каталогам сверх необходимого.
- Считайте команды shell привилегированной возможностью.
- Настраивайте права на ресурсы: файлы, коллекции, провайдеры.
- Держите `GIGA_AGENT_SECRET_KEY` в секрете.
- Не копируйте демонстрационные настройки в общий сервер без проверки.
