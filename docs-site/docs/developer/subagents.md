---
title: "Субагенты"
description: "Субагенты совместимости, глубокое исследование и зарегистрированные подграфы GigaAgent."
---

# Субагенты

Есть два связанных механизма подграфов:

- `DeepResearchModule` регистрирует подграф `deep_research` для глубокого исследования;
- `SubAgentLegacyModule` хранит субагенты совместимости из `giga_agent.modules.subagents_legacy`.

## Зарегистрированные подграфы

| Идентификатор | Источник | Точка входа |
|---|---|---|
| `deep_research` | `DeepResearchModule` | `giga_agent.modules.deep_research.graph:graph` |
| `landing` | `SubAgentLegacyModule` | `giga_agent.modules.subagents_legacy.agents.landing_agent.graph:graph` |
| `presentation` | `SubAgentLegacyModule` | `giga_agent.modules.subagents_legacy.agents.presentation_agent.graph:graph` |
| `meme` | `SubAgentLegacyModule` | `giga_agent.modules.subagents_legacy.agents.meme_agent.graph:graph` |
| `lean_canvas` | `SubAgentLegacyModule` | `giga_agent.modules.subagents_legacy.agents.lean_canvas:app` |
| `podcast` | `SubAgentLegacyModule` | `giga_agent.modules.subagents_legacy.agents.podcast.graph:graph` |

## Инструменты `DeepResearchModule`

`run_deep_research` доступен, если у пользователя выбраны языковая модель и поисковый провайдер. Инструмент подходит для сложных вопросов, где нужен план исследования, поиск по нескольким источникам, чтение и итоговый отчёт с цитированием источников.

## Инструменты модуля совместимости

Инструменты из `_get_tools()` в `SubAgentLegacyModule` становятся доступны при выполнении условий:

- `lean_canvas` — если есть языковая модель;
- `city_explore` — если есть токен 2ГИС и выполнение идёт не из командной строки;
- `podcast_generate` — если есть языковая модель и SaluteSpeech, а выполнение идёт не из командной строки;
- `create_meme` — если есть языковая модель и провайдер изображений.

`create_landing` и `generate_presentation` есть в модуле совместимости, но их регистрация как инструментов верхнего уровня отключена.

## Секреты

Субагенты совместимости объявляют секреты:

- `TWOGIS_TOKEN`;
- `SALUTE_SPEECH`;
- `SALUTE_SCOPE`;
- `SUBAGENTS_LLM`;
- `RESEARCHER_LLM`.
