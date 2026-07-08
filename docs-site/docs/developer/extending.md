---
title: "Расширение GigaAgent"
description: "Как добавлять модули, инструменты и подграфы и поддерживать документацию в актуальном состоянии."
---

# Расширение GigaAgent

Расширяйте GigaAgent через `BaseModule`: так новый код предсказуемо попадает в маршруты, инструменты, системные инструкции, миграции и сервер разработки LangGraph.

## Минимальный модуль

```python
from giga_agent.core.module import BaseModule

class MyModule(BaseModule):
    id = "my_module"
    label = "Мой модуль"
    description = "Что делает модуль"
    icon = "Sparkles"
```

Подключение в стандартный агент делается через `GigaAgent.get_modules()` или через `modules` при создании собственного экземпляра агента. Следите за уникальностью `id`: `BaseAgent` завершит инициализацию с ошибкой при дублях.

## Добавить маршрут

```python
from fastapi import APIRouter

router = APIRouter()

@router.get("/health")
async def health():
    return {"ok": True}

class MyModule(BaseModule):
    id = "my_module"

    def get_api_router(self, **kwargs):
        return router
```

Маршрут будет смонтирован как `/agent/my_module/health`, если используется стандартный префикс `/agent`. При запуске через `giga_agent dev` внешний путь обычно будет `/api/agent/my_module/health`.

## Добавить инструмент

```python
from langchain_core.tools import tool

@tool
async def my_tool(value: str) -> str:
    """Short description visible to the model."""
    return value

class MyModule(BaseModule):
    id = "my_module"
    label = "Мой модуль"

    async def _get_tools(self, user, agent, *, config=None, **kwargs):
        return [my_tool]
```

Если инструмент зависит от провайдера, сначала проверьте его доступность и возвращайте пустой список, когда условие не выполнено.

## Добавить инструкции

```python
class MyModule(BaseModule):
    id = "my_module"

    async def get_instructions(self, user, agent, state=None, config=None, **kwargs):
        return "Use my_tool only when the user asks for ..."
```

Инструкции активных модулей добавляются в базовую системную инструкцию, если модуль не отключён пользователем.

## Добавить подграф

```python
class MyModule(BaseModule):
    id = "my_subgraphs"

    def get_subgraphs(self, **kwargs):
        return {
            "my_subgraph": "my_package.my_module.graph:graph",
        }
```

Значение — путь импорта формата `python.module:variable`.

## Интеграции и виджеты

Для внешних сервисов и наглядных результатов есть готовые слои: модуль-интеграция с провайдером подключения попадает в каталог коннекторов автоматически (см. [Модули-интеграции](./integrations.md)), а инструмент, вернувший payload с маркером `widget`, отображается карточкой в чате (см. [GenUI](./genui.md)).

## Проверка перед документацией

Перед тем как описывать новую возможность:

1. Проверьте, что модуль зарегистрирован в агенте.
2. Проверьте, что маршрут, инструмент или подграф реально появляется через рабочий путь выполнения.
3. Опишите условия доступности: провайдеры, секреты, права, отличия интерфейса и командной строки.
4. Обновите документацию вместе с изменением, чтобы не накапливать неточные утверждения.
