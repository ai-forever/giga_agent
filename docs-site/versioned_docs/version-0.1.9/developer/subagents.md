---
title: "Субагенты"
description: "Субагенты совместимости и зарегистрированные подграфы GigaAgent 0.1.9."
---

# Субагенты

:::info[Документация стабильного релиза PyPI]
Эта страница описывает опубликованный PyPI-пакет `giga-agent==0.1.9`. Для актуального состояния репозитория переключитесь на версию **main**.
:::

В версии `0.1.9` субагенты находятся в модуле `giga_agent.modules.subagents_legacy`. Это модуль совместимости: он сохраняет существующие сценарии субагентов и их подграфы.

## Зарегистрированные подграфы

`SubAgentLegacyModule.get_subgraphs()` регистрирует:

| Идентификатор | Точка входа |
|---|---|
| `landing` | `giga_agent.modules.subagents_legacy.agents.landing_agent.graph:graph` |
| `presentation` | `giga_agent.modules.subagents_legacy.agents.presentation_agent.graph:graph` |
| `meme` | `giga_agent.modules.subagents_legacy.agents.meme_agent.graph:graph` |
| `lean_canvas` | `giga_agent.modules.subagents_legacy.agents.lean_canvas:app` |
| `podcast` | `giga_agent.modules.subagents_legacy.agents.podcast.graph:graph` |

## Инструменты модуля

Инструменты из `_get_tools()` становятся доступны при выполнении условий:

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
