<h1 align="center">Универсальный AI-агент</h1>

<picture>
  <source media="(prefers-color-scheme: light)" srcset="https://github.com/ai-forever/giga_agent/blob/v0.1/docs/images/giga-agent_light_logo.png">
  <source media="(prefers-color-scheme: dark)" srcset="https://github.com/ai-forever/giga_agent/blob/v0.1/docs/images/giga-agent_dark_logo.png">
  <img alt="Shows a black and red Giga Agent Logo in light color mode and a white and red in dark color mode" src="docs/images/giga-agent_dark_logo.png"  width="full">
</picture>

[ [Русский](https://www.zdoc.app/ru/ai-forever/giga_agent) | 
[中文](https://www.zdoc.app/zh/ai-forever/giga_agent) | 
[English](https://www.zdoc.app/en/ai-forever/giga_agent) | 
[Español](https://www.zdoc.app/es/ai-forever/giga_agent) ]

<p align="center">
  <a href="https://ai-forever.github.io/giga_agent/">
    <img src="https://img.shields.io/badge/%F0%9F%93%96%20Документация-online-dc2626?style=for-the-badge&logo=docusaurus&logoColor=white" alt="Документация GigaAgent">
  </a>
</p>

**GigaAgent может решать самые разные задачи, используя более 30 встроенных инструментов и субагентов.**

[![Deploy to DO](https://www.deploytodo.com/do-btn-blue.svg)](https://cloud.digitalocean.com/apps/new?repo=https://github.com/ai-forever/giga_agent/tree/main)

Например, он позволит вам работать с большими файлами через код (Excel-файл с десятками тысяч строк), [придумать мем](docs/examples/memes/chat.pdf), [описать бизнес-модель стартапа](docs/examples/lean_canvas/lean_canvas.pdf) или [создать лендинг](docs/examples/changelog_landing/changelog_landing.pdf).
Для этого GigaAgent использует субагентов, REPL-среду для исполнения кода и сторонние сервисы.

GigaAgent разработан в рамках проекта [GigaChain](https://github.com/ai-forever/gigachain) – открытого набора инструментов для разработки LLM-приложений и мультиагентных систем.

GigaAgent умеет:

- работать с разными моделями, [доступными в LangChain](https://python.langchain.com/docs/integrations/chat/#all-chat-models): GigaChat, ChatGPT, Anthropic и другими
- исполнять код в чате с помощью REPL-среды, подобной [блокнотам Jupyter](https://jupyter.org/)
- подключать внешние сервисы через каталог коннекторов: Яндекс.Почту, Календарь и Диск, VK, GitHub и другие серверы MCP
- использовать инструменты для анализа данных, генерации изображений, создания презентаций и лендингов
- генерировать изображения с помощью разных провайдеров: GigaChat, FusionBrain, OpenAI
- показывать результаты интерактивными виджетами в чате: письма, календарь, файлы
- выполнять задачи по расписанию и отвечать в Telegram через каналы
- работать локально или в облаке, с помощью Docker
- применять знания из ваших документов с помощью RAG

## Демо

<img src="docs/images/demo.gif" width=500>

Примеры работы с GigaAgent в формате PDF:

- [кластеризация комментариев в VK](docs/examples/cluster_comments/clusters_ru.pdf)
- [анализ настроений комментариев в VK и вывод основных жалоб](docs/examples/sentiment_analysis/sentiment_analysis.pdf)
- [создание сайта со списком изменений, созданным на основе последних закрытых PR](docs/examples/changelog_landing/changelog_landing.pdf)

Примеры работы субагентов, а также подробная информация о них — в разделе [Субагенты](SUBAGENTS.md).
Описание доступных инструментов и процесса создания новых инструментов можно найти в разделе [Инструменты в GigaAgent](TOOLS.md)

## Быстрый старт

1. Установите пакет:
  ```bash
   uv add giga_agent
  ```
  Для локальной изолированной среды через Jupyter установите дополнение:
  ```bash
   pip install -U "giga-agent[jupyter]"
  ```
2. Запустите dev-сервер:
  ```bash
   uv run giga_agent dev
  ```
3. Откройте в браузере:
  ```text
   http://localhost:9090
  ```

Логин по умолчанию при первой инициализации (когда в БД нет пользователей):

- `admin@example.com`
- `giga_agent_admin`

Для первого ответа агента откройте настройки и добавьте подключение к провайдеру моделей (вкладка «Подключения»), затем языковую модель. Для работы с документами и памятью понадобятся Embeddings, для выполнения кода — Sandbox. Пошагово: [Первый чат](https://ai-forever.github.io/giga_agent/docs/next/quickstart/first-chat).

## Запуск через Docker

Standalone-образ запускает UI и API одним процессом на порту `9090`, использует SQLite и хранит данные в `/data/.giga_agent`:

```bash
docker run --rm -it \
  -p 9090:9090 \
  -v giga-agent-data:/data/.giga_agent \
  ghcr.io/<owner>/<repo>:latest
```

Docker Compose поднимает отдельные сервисы (nginx, PostgreSQL, Redis, Qdrant) для самостоятельного размещения:

```bash
cp .env.example .env   # заполните минимум GIGA_AGENT_SECRET_KEY
make build
make up                # UI на http://localhost:8123
```

Подробности и переменные окружения: [Запуск через Docker](https://ai-forever.github.io/giga_agent/docs/next/quickstart/docker) и [env-референс](docs/configuration/env.md).

## Документация

Полная документация живёт на отдельном сайте — <https://ai-forever.github.io/giga_agent/> — в двух версиях (стабильный пакет PyPI и текущая ветка `main`) и на двух языках:

- [Быстрый старт](https://ai-forever.github.io/giga_agent/docs/next/quickstart/local) — установка, первый чат, Docker
- [Руководство пользователя](https://ai-forever.github.io/giga_agent/docs/next/user-guide/chat) — чат, проекты, коннекторы, сервисы Яндекса, виджеты, задачи по расписанию, каналы
- [Возможности и требования](https://ai-forever.github.io/giga_agent/docs/next/user-guide/capabilities) — что работает сразу и что нужно настроить
- [Разработчикам](https://ai-forever.github.io/giga_agent/docs/next/developer/architecture) — архитектура, модули, интеграции, GenUI
- [Эксплуатация](https://ai-forever.github.io/giga_agent/docs/next/operations/configuration) — конфигурация, изолированная среда, совместный сервер, устранение неполадок

## Технологический стек

### Backend

- **Python 3.11+** — современный Python с async/await
- **[LangGraph 1.0.8](https://github.com/langchain-ai/langgraph)** — state machine для AI-агентов от LangChain
- **[FastAPI](https://fastapi.tiangolo.com/)** — высокопроизводительный веб-фреймворк
- **[SQLAlchemy 2.0](https://www.sqlalchemy.org/)** — async ORM с поддержкой SQLite и PostgreSQL
- **[Alembic](https://alembic.sqlalchemy.org/)** — система миграций с multi-scope поддержкой
- **Redis** — кэширование и distributed locks (через [cashews](https://github.com/Krukov/cashews))
- **[Qdrant](https://qdrant.tech/)** — векторное хранилище для RAG и памяти
- **[E2B](https://e2b.dev/)** — облачные sandboxes для безопасного выполнения кода
- **Docker SDK** — управление локальными sandbox-контейнерами
- **Jupyter Server** — optional extra `giga-agent[jupyter]` для admin-only `local_jupyter` sandbox с одним singleton-процессом на агент

### Frontend

- **[React 19](https://react.dev/)** — последняя версия React
- **[TypeScript 5.8](https://www.typescriptlang.org/)** — статическая типизация
- **[Vite 7](https://vitejs.dev/)** — быстрая сборка и dev-сервер
- **[Tailwind CSS 4](https://tailwindcss.com/)** — utility-first CSS фреймворк
- **[Radix UI](https://www.radix-ui.com/)** — headless UI компоненты
- **[LangGraph SDK](https://github.com/langchain-ai/langgraph/tree/main/libs/sdk-js)** — интеграция с LangGraph для streaming
- **[Framer Motion](https://www.framer.com/motion/)** — анимации

### Инфраструктура

- **Docker & Docker Compose** — контейнеризация
- **Nginx** — reverse proxy для production
- **PostgreSQL** — production база данных (dual-database: LangGraph + app)
- **SQLite** — development база данных

## Для разработчиков

Ключевые CLI-команды:

- Проверка состояния миграций:
  ```bash
  giga_agent check
  ```
- Применение миграций:
  ```bash
  giga_agent migrate
  ```
- Генерация миграций:
  ```bash
  giga_agent makemigrations
  ```
- Проксирование Alembic-команд:
  ```bash
  giga_agent alembic --scope core upgrade head
  ```
- Экспорт langgraph-конфига:
  ```bash
  giga_agent export-langgraph-json
  ```

Об устройстве модулей, инструментов и точках расширения — в [разделе для разработчиков](https://ai-forever.github.io/giga_agent/docs/next/developer/architecture).

## Дополнительные материалы

- 📖 Полная документация: <https://ai-forever.github.io/giga_agent/>
- Субагенты: [SUBAGENTS.md](SUBAGENTS.md)
- Инструменты: [TOOLS.md](TOOLS.md)
- Env-референс: [docs/configuration/env.md](docs/configuration/env.md)
- Observability для локального запуска: [docs/configuration/observability-local.md](docs/configuration/observability-local.md)

## Contributing

PR и issue приветствуются. Для больших изменений лучше заранее описать proposal в issue с ожидаемым эффектом и планом валидации.

## License

Проект распространяется под лицензией MIT. См. файл [LICENSE](LICENSE).
