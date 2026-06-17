# Deep Research — архитектура модуля

## Назначение

Модуль `giga_agent.modules.deep_research` — режим **глубокого исследования**. Пайплайн `plan → search → read → reflect → compose` возвращает структурированный markdown-отчёт с нумерованными цитатами `[N]`.

## Почему отдельный модуль (а не расширение `researcher_agent`)

В проекте уже есть `researcher_agent` в `subagents_legacy` на базе библиотеки [`deepagents`](https://github.com/langchain-ai/deepagents). Принципиальные отличия нового `deep_research`:

| Фича                                            | researcher_agent (legacy)         | deep_research (новый)       |
| ----------------------------------------------- | --------------------------------- | --------------------------- |
| Чтение страниц через Jina Reader                | ❌ (только сниппеты поисковика)    | ✅                           |
| Структурированный State (plan + sources)        | ❌ (virtual files + messages)      | ✅ (TypedDict)               |
| Параллельный search и read                      | ❌                                 | ✅ (`asyncio.gather` + sem)  |
| Стриминг плана/источников в UI                  | ❌                                 | ✅ (`push_ui_message`)       |
| Контроль бюджета                                | ❌ (только `recursion_limit`)      | ✅ (итерации/источники)     |

Старый `researcher_agent` остаётся для сценария «простой ресёрч без чтения страниц».

## Зафиксированные архитектурные решения

1. **Отдельный модуль** `modules/deep_research/` (не внутри `subagents_legacy`).
2. **LLM**: `resolve_user_llm(user)` — дефолтная юзерская модель. Отдельный secret `DEEP_RESEARCH_LLM` — в post-MVP.
3. **Формат отчёта**: markdown-файл, сохраняется через `upload_files_for_config_user` как `FileResponse`, отдаётся пользователю как `![отчёт](attachment:<path>)`. HTML-лендинг — post-MVP.
4. **Цитаты**: inline `[1]`, `[2]` в тексте; секция `## Источники` в конце с полным списком.
5. **Язык отчёта**: определяется в промпте composer'а — «на языке исходного запроса».
6. **RAG-сохранение**: в MVP нет. Post-MVP — опция складывать прочитанные страницы в RAG-коллекцию треда.
7. **Фильтр доменов**: в MVP нет. Post-MVP.
8. **Свежесть**: в MVP без ранжирования. Полагаемся на сортировку поисковика.
9. **Параллелизм**: search — один батч `engine.search(all_queries)` (движок сам параллелит); read — через **локальный cap** `DEEP_RESEARCH_FETCH_CONCURRENCY_CAP = 3` (free-tier `r.jina.ai` отдаёт 429 при >3 параллельных), поверх `min(user_setting, 3)`. На `429/5xx/408/425` — retry с экспоненциальным backoff (`FETCH_RETRY_ATTEMPTS = 3`, базовая задержка 1.2с × 2^attempt × джиттер 0.5–1.5x). На 403 — не ретраим, это forbidden сайт.
10. **Дедупликация**: по нормализованному URL (без tracking-параметров: `utm_*`, `fbclid`, `gclid`, `yclid` и т. д.) + по домену внутри одного подвопроса.
11. **Бюджеты (дефолты)**: `max_iterations=3`, `max_subquestions=6`, `sources_per_subq=5`, `max_sources=40`.
12. **Scraper-логика**: переиспользуем приватные хелперы из `modules.scraper.tool` (`_load_via_jina_reader`, `_process_url`, `_resolve_fast_llm`). Не вызываем `@tool get_urls` напрямую — нужен прямой путь без LLM-обёртки вокруг сам-вызова.
13. **Доступность tool**: `run_deep_research` регистрируется только при `user.llm_id is not None and user.search_engine_id is not None`.
14. **Возможность продолжения**: tool принимает `thread_id`, чтобы можно было «добавь ещё, углуби такой-то подвопрос».
15. **Tool-payload wrapping**: при возврате большого payload (>25KB по умолчанию, см. `GIGA_AGENT_TOOL_MAX_SIZE`) middleware `middlewares/tool_result.py` оборачивает его в `{data: <original>, result_path: <path>, message: <instructions>}` и сохраняет полный результат в sandbox как JSON. Frontend-рендер **должен** читать `parsedPayload.data?.plan ?? parsedPayload.plan` — иначе план/источники исчезнут на больших прогонах. Это уже реализовано в `ToolMessage.tsx` для `deepResearchFinalPlan`.
16. **Как пользователь понимает, что пошёл deep research** (дёшево, до M4):
    - `front/src/config.ts` → `TOOL_MAP["run_deep_research"] = "Глубокое исследование"` — в заголовке tool-блока показывается «Инструмент выполняется: Глубокое исследование».
    - `PROGRESS_AGENTS["run_deep_research"]` — человекочитаемые подписи к узлам (`planner`→«Раскладываю запрос на подвопросы» и т. д.).
    - В `DEEP_RESEARCH_INSTRUCTIONS` модулю прописано: перед вызовом tool'а LLM **обязан** написать пользователю короткую строчку-прелюдию («Запускаю глубокое исследование — займёт 1–2 минуты»).
17. **Фильтр доменов**: в `utils.py` захардкожен `BLOCKED_DOMAIN_SUFFIXES` — auth-walled социальные (vk/facebook/instagram/twitter/tiktok/t.me), video-only (youtube/youtu.be), reddit-без-авторизации, известные 403-через-Jina (yaplakal). `is_blocked_domain(url)` проверяется в `search_node` до накопления sources. Отсекает бесполезные URL на фазе поиска, экономит Jina + LLM-суммаризацию.
18. **Агент-критик после compose**: граф стал `compose → critique → {compose(revise) | finalize}`. `critique_node` через `bind_tools(submit_critique)` выдаёт `verdict: accept|revise` + `critique_text`. При revise — draft возвращается в `compose` с критикой в state; `revision_count` инкрементится, кап `max_revisions=1`. `finalize_node` отделяет upload в sandbox от compose (нужно, чтобы revise-петля не плодила файлы). State расширен: `report_draft: str | None`, `critique: str | None`, `critique_verdict`, `revision_count: int`. На любом фейле LLM/tool-call → graceful accept (не блокируем финал).
19. **Query rewrite + diverse queries в planner** (единое требование, живёт в узле `planner`):
    - Для каждого подвопроса планировщик выдаёт **3–4 разных поисковых запроса**: разные формулировки, разные ключевые слова, **разные языки** (для интернациональных тем — обязательно английский; для российских реалий — русский).
    - Motivation: один запрос хитает одну SEO-кластеризацию; 3–4 разных угла дают ширину покрытия. Языковая диверсификация критична, т. к. GigaChat по дефолту клепает только русские queries — надо форсить в промпте + few-shot.
    - Реализовано **внутри одного узла planner** (не отдельным `rewrite`-узлом), чтобы не плодить LLM-вызовы. Если few-shot не сработает — выносим в отдельный узел.
    - **Бюджет**: с учётом `6 подвопросов × 3–4 query × ~5 результатов = 90–120 URL`, урезаем `sources_per_subq` до 3 и добавляем после дедупа rank+select top-N по score поисковика.

## Структура каталога

```
modules/deep_research/
├── __init__.py            # export DeepResearchModule
├── module.py              # DeepResearchModule(BaseModule)
├── config.py              # State, ConfigSchema, бюджеты
├── prompts.py             # промпты (planner, reflect, compose)
├── graph.py               # StateGraph + graph + @tool run_deep_research
├── utils.py               # normalize_url, dedup_sources
├── nodes/
│   ├── __init__.py
│   ├── planner.py         # декомпозиция запроса (LLM)
│   ├── search.py          # прямой вызов SearchEngineManager
│   ├── read.py            # прямой вызов Jina Reader + LLM-суммаризация
│   ├── reflect.py         # оценка покрытия, решение loop/stop
│   └── compose.py         # финальный markdown с цитатами
└── ARCHITECTURE.md
```

## Поток (happy path, одна итерация)

1. **planner** — LLM со structured output:
   ```json
   {"sub_questions": [{"text": "...", "queries": ["q1", "q2"]}, ...]}
   ```
2. **search** — собирает все `queries`, одним батчем `engine.search(all_queries)`. Раскидывает результаты по `sub_question_ids`, дедуп по URL, ограничение `sources_per_subq`.
3. **read** — параллельный Jina Reader (общий семафор `fetch_sem`) + LLM-суммаризация страниц (семафор `summarize_sem`). Пишет `Source.summary`.
4. **reflect** — LLM смотрит sources, решает `stop` или `new_queries`. В M1/M2 — заглушка со `stop=True`.
5. **compose** — LLM генерирует markdown, привязывает `[N]`-цитаты. Сохраняется через `upload_files_for_config_user` в sandbox.

## Стриминг в UI

Tool `run_deep_research` запускает субграф через `get_client(runtime.config).runs.stream()` и перехватывает `updates`-чанки. Для каждого завершённого узла шлёт:

```python
push_ui_message("agent_execution", {
    "agent": "run_deep_research",
    "node": <name>,
    "tool_call_id": ...,
    "plan": ...,      # live plan
    "sources": ...,   # накопленные источники
    "iteration": ...,
})
```

Frontend в M1 использует дефолтный рендер `ToolMessage.tsx` — пользователь видит прогресс по узлам. В M4 — кастомная карточка с live-планом и списком источников.

## Регистрация субграфа

1. `DeepResearchModule.get_subgraphs()` возвращает `{"deep_research": "giga_agent.modules.deep_research.graph:graph"}`.
2. Модуль добавлен в `GigaAgent.get_modules()` в `agents/giga_agent.py`.
3. В `backend/langgraph.json` добавлен entry `"deep_research"`. Для автогенерации: `giga_agent export-langgraph-json`.

## TODO post-MVP

См. task #5 в TaskList. Кратко:
- RAG: складывать прочитанные страницы в коллекцию `rag-thread-<thread_id>`.
- Ранжирование источников (свежесть + similarity-скор).
- Secret `DEEP_RESEARCH_LLM` — дешёвая модель для planner/reflect, дорогая — для compose.
- HTML-отчёт через `create_landing` как финальный узел.
- Retry + fallback-поисковик.
- Token accounting (cost-репортинг).
- i18n промптов.
- **Tool-result clearing middleware** (компакция истории): перед каждым LLM call проходим по `state.messages`, для каждого `ToolMessage` старше N turns (кроме последнего) заменяем `content` на `{"stale": true, "result_path": ..., "hint": "use python to read if needed"}`. Payload уже сохраняется в sandbox через `tool_result.py` (решение #15). Экономит контекст на длинных тредах с несколькими `run_deep_research` / search calls. Параметр N — через settings.
- (сделано) Фильтр доменов — решение #17.
- (сделано) Critic-агент — решение #18.