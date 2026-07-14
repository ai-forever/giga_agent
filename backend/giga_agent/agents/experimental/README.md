# Экспериментальный режим (`giga_agent_experimental`)

Граф-обёртка, которая работает как **презентационная прослойка** между реальным
агентом `giga_agent` и пользователем. Вместо «сырого» агента (тул-колы,
размышления, черновой русский) пользователь видит:

- живой статус того, **чем сейчас занят** агент, в строке «Думаю…» (обновляется
  быстрой моделью ~раз в 10 секунд);
- каждый ответ агента, **переписанный** моделью-редактором (GigaChat-3-Ultra):
  убраны опечатки/орфографические ошибки, текст сделан «более русским»;
- проброшенные виджеты / MCP-app из тул-результатов (рендерятся как обычно).

Форма внешнего треда: `HUMAN [AI] [AI] [Tool с виджетом] [AI]`.

Режим включается только при `GIGA_AGENT_EXPERIMENTAL_MODE=True` — фронт по этому
флагу (через app-config) подключается к графу `giga_agent_experimental` вместо
`giga_agent`.

## Как это устроено

Обёртка переиспользует принятый в репозитории паттерн работы с сабграфом через
LangGraph **SDK** (как `deep_research`): реальный `giga_agent` гоняется отдельным
**фоновым** ран'ом в отдельном (скрытом) треде, а внешний граф следит за ним
через `client.threads.get_state` и переотправляет прогресс во фронт через
`push_ui_message`. Композиции in-process (сабграф как нода) нет — её нет и во всём
проекте.

Внешний граф — стейт-машина `kickoff → pump →(loop)→ END`, а не одна длинная
нода. Это нужно ради **инкрементальных чекпойнтов** (см. ниже).

### Ноды

- **`kickoff`** — берёт последнее human-сообщение внешнего треда; создаёт (или
  переиспользует на последующих ходах) скрытый inner-тред `giga_agent`
  (`metadata={"experimental_inner": True}`); запускает фоновый ран
  (`client.runs.create(assistant_id="giga_agent", ...)`); сохраняет
  `inner_thread_id` / `inner_run_id` / `processed_inner_ids` в состоянии.
  **Пробрасывает во вход inner-рана всё, что пришло в submit'е фронта:**
  - `additional_kwargs` human-сообщения (`files` — вложения, `selected` —
    указанные вложения, `user_input`) — тем же shape'ом `{"type":"human",
    "content", "additional_kwargs"}`, что шлёт фронт, поэтому inner-граф читает
    их как обычно (`_build_file_prompt`/`_build_selected_prompt`);
  - `collections` (RAG) и `mcp_tools` из входа submit'а (они в `ExperimentalState`,
    иначе обёртка их проглотит);
  - whitelisted `configurable`: `deep_research_forced` (режим исследования),
    `selected_skills` (скилы) + принудительный `auto_approve`.
- **`pump`** («довести inner-ран до следующего всплывающего элемента и
  закоммитить его») — в цикле:
  1. опрашивает `client.threads.get_state(inner_thread_id)`; между опросами
     ~раз в 10 секунд пушит статус (`push_ui_message("experimental_status",
     {"text": ...})`, эфемерно — без чекпойнта), сгенерированный быстрой моделью
     по последним действиям агента;
     Статусы берут контекст не только из закоммиченного стейта, но и из **живого
     messages-стрима**: параллельно `pump` держит фоновую задачу `_consume_live`,
     которая `join_stream`'ит inner-ран (`stream_mode="messages"`, не буферизован
     — токены «с этого момента») и пишет последний partial в `live["text"]`. Это
     чинит «залипание» статуса во время долгого ризонинга, когда в `get_state`
     ещё ничего нового не закоммичено. Из partial-чанков собирается не только
     `content`/`reasoning_content`, но и **стримящиеся аргументы тул-колов**
     (накопленная строка из `tool_call_chunks`, распарсенные `tool_calls`,
     частичный JSON из `invalid_tool_calls`) — статус видит, какой инструмент и с
     чем агент формирует прямо сейчас. Задача отменяется при возврате/отмене
     pump; inner-ран при этом НЕ отменяется (`cancel_on_disconnect=False`).
     Статус считается ТОЛЬКО по текущему ходу: `_push_status` берёт inner-сообщения
     после последнего human-сообщения (на доп. сообщении прошлые ходы игнорируются),
     а само user-сообщение подаётся отдельно с пометкой «Запрос пользователя»,
     чтобы модель могла его обыграть, пока конкретных действий ещё нет.
  2. находит следующее inner-сообщение с id ∉ `processed_inner_ids`, которое либо
     **AI с непустым content** (после `strip_thinking`) → переписывает моделью-
     редактором (`astream`, токены стримятся во внешний ран), либо
     **ToolMessage-виджет** (`additional_kwargs.response_widget` / `mcp_ui`-
     аттачмент) → синтезирует AI-заглушку с tool_call + пробрасывает ToolMessage;
  3. возвращает всплывший элемент в `{"messages": [...]}` → **один чекпойнт на
     один всплывший элемент**;
  4. на отмене (`CancelledError`) — best-effort `client.runs.cancel` фонового
     inner-рана.
- **`route_after_pump`** — `done → END`, иначе снова `pump`.

### Персистентность (инкрементальные чекпойнты)

- Граф компилируется **без чекпойнтера** (`workflow.compile()`), как
  `giga_agent`/`deep_research`; per-thread чекпойнтер инжектит сервер (Aegra).
  Состояние снапшотится на границе каждого super-step'а.
- Число чекпойнтов ≈ числу всплывших сообщений (несколько на ход), НЕ по одному на
  poll-тик: ожидание и статусы происходят ВНУТРИ одного вызова `pump` без
  чекпойнта. Это сознательно ограничено (`recursion_limit=200`) — см. инцидент с
  OOM при рануэй-цикле и тысячах чекпойнтов.
- Сообщения, порождённые `astream` внутри ноды, стримятся в UI, но в канал
  `messages` попадают **только если нода их вернёт** — поэтому `pump` всегда
  возвращает всплывший элемент в state.
- `processed_inner_ids` — курсор: на перезагрузке/резюме уже всплывшие элементы
  уже в state, `pump` продолжает с курсора. **`kickoff` сохраняет курсор между
  ходами** (не сбрасывает в `[]`) — иначе на доп. сообщении inner-тред уже
  содержит все прошлые сообщения и `pump` всплыл бы их заново (дубли старых AI).
- Всплывающие AI-сообщения помечаются `additional_kwargs["rendered"] = True`,
  чтобы на перезагрузке фронт показывал их сразу целиком (без «печатной машинки»).
- Завершение (`done`) определяет СЛЕДУЮЩИЙ `pump` по свежему снапшоту — иначе
  можно завершиться раньше времени (пока шёл await переписывания, inner-ран мог
  закоммитить ещё сообщения).

### Авто-approve (autonomous)

Inner-ран `giga_agent` фоновый и без UI одобрения тул-колов, поэтому запускается в
**автономном режиме**: `kickoff` ставит `auto_approve: True` в metadata inner-треда
и передаёт `config.configurable.auto_approve=True` в `runs.create`. Тогда
`ToolResultMiddleware.after_model` не делает `interrupt` для серверных тулов
(тот же механизм, что у scheduled-задач и Telegram-каналов).

Ограничение: клиентские MCP-тулы (`frontend_actions`) всё равно требуют
`interrupt` — их некому исполнить в фоне, поэтому такой inner-ран уйдёт в статус
`interrupted`, а `pump` завершит внешний ран (`done`). Для v1 это осознанное
ограничение.

### Остановка

Стоп на фронте отменяет внешний ран → исполняемый `pump`/`kickoff` получает
`CancelledError` → в обработчике вызывается `client.runs.cancel(inner_thread_id,
inner_run_id)`, что гасит фоновый inner-ран.

### Название треда

У обёртки нет `ThreadTitleMiddleware`, поэтому название внешнего треда берётся из
inner-треда: `giga_agent` генерит `thread_title` в metadata своего треда, а `pump`
копирует его в metadata внешнего треда (`_sync_title_from_inner` →
`update_thread_metadata(outer_thread_id, {"thread_title": ...})`). Делается один
раз (флаг `title_synced` в state), сайдбар читает `metadata.thread_title`.

### Скрытие inner-тредов

Inner-тред `giga_agent` не засоряет сайдбар: сайдбар фильтрует треды по
`graph_id`, а в экспериментальном режиме он запрашивает
`graph_id="giga_agent_experimental"`, поэтому inner-треды (`graph_id="giga_agent"`)
не попадают в список. Метка `metadata.experimental_inner` оставлена как
запасной маркер, если понадобится явное исключение.

## Dev-просмотр оригинального треда

Чтобы посмотреть **сырой** inner-тред `giga_agent` (без переписывания, с
тул-колами и размышлениями) в обычном UI — даже когда включён экспериментальный
режим — есть dev-маршруты, которые ВСЕГДА рендерят оригинальный `Chat`
(`assistantId="giga_agent"`):

- `/dev/threads/<inner_thread_id>` — открыть конкретный оригинальный тред;
- `/dev` — новый оригинальный тред.

`inner_thread_id` лежит в state внешнего треда. Для удобства во внешнем чате
(в экспериментальном режиме, когда inner-тред уже создан) показывается маленькая
ссылка «dev: оригинальный тред ↗», открывающая `/dev/threads/<inner_thread_id>`
в новой вкладке.

## Модели

Две модели GigaChat инстанцируются **напрямую** из env (как `backend/t.py`:
`GigaChat(model=<env>, verify_ssl_certs=False)`), креды берутся из `GIGACHAT_*`.
Это НЕ проходит через per-user коннектор/DB — режим использует одну env-модель.

- `GIGA_AGENT_EXPERIMENTAL_REWRITE_MODEL` (дефолт `GigaChat-3-Ultra`) — переписывание.
- `GIGA_AGENT_EXPERIMENTAL_STATUS_MODEL` (дефолт `GigaChat-3-Pro`) — статусы.
  ⚠️ Строки `GigaChat-3-Pro` в репозитории нет — дефолт-догадка, при отказе SDK
  задайте реальное имя быстрой модели через env.

## Env

| Переменная | Дефолт | Назначение |
|---|---|---|
| `GIGA_AGENT_EXPERIMENTAL_MODE` | `False` | Включает режим (фронт → `giga_agent_experimental`) |
| `GIGA_AGENT_EXPERIMENTAL_REWRITE_MODEL` | `GigaChat-3-Ultra` | Модель-редактор |
| `GIGA_AGENT_EXPERIMENTAL_STATUS_MODEL` | `GigaChat-3-Pro` | Быстрая модель статусов |

Плюс должны быть заданы `GIGACHAT_*` креды в env.

## Затронутые файлы

**Бэкенд**
- `agents/experimental/graph.py` — граф (этот модуль).
- `agents/experimental/module.py` — `ExperimentalModule.get_subgraphs()` регистрирует граф.
- `agents/giga_agent.py` — модуль добавлен в `get_modules()`.
- `conf.py` — три настройки + экспортированные константы.
- `runtime_config.py` — `experimentalMode` в app-config.
- `utils/messages.py` — общий `strip_thinking` (telegram-утиль переиспользует).
- `langgraph.json` — перегенерирован (содержит `giga_agent_experimental`).

**Фронт**
- `config.ts` — `EXPERIMENTAL_MODE`.
- `App.tsx` — маршруты на `ExperimentalChat` при флаге.
- `components/ExperimentalChat.tsx` — обёртка над `Chat` (`assistantId="giga_agent_experimental"`).
- `components/Chat.tsx` — опциональный проп `assistantId` (дефолт прежний).
- `components/ThinkingIndicator.tsx` — показывает пуш-статус в строке «Думаю…».
- `components/Sidebar.tsx` — `currentGraphId` → `giga_agent_experimental`.

## Регенерация `langgraph.json`

После правок сабграфов:

```bash
cd backend && giga_agent export-langgraph-json
```

## Что проверить вживую

1. End-to-end при `GIGA_AGENT_EXPERIMENTAL_MODE=True` (+ `GIGACHAT_*`): статусы,
   стриминг переписанных ответов, проброс виджетов, стоп гасит inner-ран,
   перезагрузка в середине рана показывает уже всплывшие элементы, доп. сообщение
   переиспользует inner-тред.
2. Имя быстрой модели (`GigaChat-3-Pro`?).
3. Что Aegra принимает фоновый `runs.create` + polling `threads.get_state` +
   `runs.cancel` (стандартный протокол, но `deep_research` использует `runs.stream`).
