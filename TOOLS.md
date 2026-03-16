# Инструменты в GigaAgent

## Расположение инструментов в репозитории

Мы поддерживаем три уровня инструментов:

* **LLM‑tools** — функции, которые модель может вызывать напрямую через tool‑calling при выполнении графа. 
* **REPL‑tools** — функции, доступные коду, исполняемому в изолированном REPL. Их задача — дать возможность вызова бэкенд-логики с секретами (токены, env-переменные). Сейчас repl-тулы позволяют вызывать LLM: получать эмбеддинги, делать суммаризацию, анализ и пр.

---

## Как добавить **новый LLM‑tool**

**TL;DR:** создайте функцию с декоратором `@tool` → создайте модуль с `BaseModule` → зарегистрируйте модуль в `GigaAgent`.

### Пошаговая инструкция

1. **Создайте файл с инструментами**
   
   Создайте файл `tools.py` в вашем модуле, например `agent/my_module/tools.py`:

```python
from langchain_core.tools import tool
from typing import Optional

@tool
def read_file(file_path: str, length: int = 100, start_position: int = 0) -> str:
    """
    Читает содержимое файла с указанной позиции и длиной.
    
    Args:
        file_path: Путь до файла для чтения
        length: Максимальное количество символов для чтения (по умолчанию 100)
        start_position: Позиция начала чтения в файле (по умолчанию 0)
    
    Returns:
        Содержимое файла в виде строки
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            f.seek(start_position)
            content = f.read(length)
        return content
    except FileNotFoundError:
        return f"Ошибка: Файл '{file_path}' не найден"
    except Exception as e:
        return f"Ошибка при чтении файла: {str(e)}"

@tool
def list_files(directory_path: Optional[str] = None) -> str:
    """
    Получает список файлов в указанной директории или в текущей директории.
    
    Args:
        directory_path: Путь к директории (если None, используется текущая директория)
    
    Returns:
        Список файлов в формате строки
    """
    # Ваша реализация
    return "Список файлов"
```

**Важные моменты:**
- Используйте декоратор `@tool` из `langchain_core.tools`
- Обязательно добавьте docstring — он используется моделью для понимания, что делает инструмент
- Опишите все параметры в формате Google-style docstring
- Обрабатывайте ошибки и возвращайте понятные сообщения

2. **Создайте модуль**

   Создайте файл `module.py` в том же пакете:

```python
from __future__ import annotations

from typing import List

from giga_agent.core.module import BaseModule
from giga_agent.models import UserShort
from langchain_core.tools import BaseTool

from .tools import read_file, list_files


class MyToolsModule(BaseModule):
    id: str = "my_tools"  # Уникальный идентификатор модуля

    async def get_tools(
        self,
        user: UserShort | None,
        agent: "BaseAgent",
    ) -> List[BaseTool]:
        """Возвращает список инструментов для агента."""
        return [read_file, list_files]
```

**Ключевые элементы:**
- Наследуйтесь от `BaseModule`
- Задайте уникальный `id` для модуля
- Реализуйте метод `get_tools()`, который возвращает список инструментов
- Метод `get_tools()` получает информацию о пользователе (`user`) и самом агенте (`agent`), что позволяет динамически настраивать инструменты

3. **Зарегистрируйте модуль в агенте**

   В вашем файле с определением агента (например, `agent.py`):

```python
from giga_agent.agents.giga_agent import GigaAgent

from .my_module.module import MyToolsModule

agent = GigaAgent(modules=[MyToolsModule()])

graph, app = agent.graph, agent.app
```

4. **Проверьте работу**

   Запустите агента и проверьте, что инструменты доступны:
   
   - Агент должен видеть ваши инструменты в списке доступных tools
   - Модель должна быть способна вызвать их по имени и описанию
   - Проверьте логи выполнения, чтобы убедиться, что вызовы проходят корректно

### Полный пример

Смотрите рабочий пример в [`examples/agent_with_tools/`](examples/agent_with_tools/):

```
examples/agent_with_tools/
├── agent/
│   ├── __init__.py
│   ├── agent.py              # Определение агента
│   └── with_tool/
│       ├── __init__.py
│       ├── module.py          # Модуль с get_tools()
│       └── tools.py           # Определение инструментов
└── pyproject.toml
```

### Динамическое подключение инструментов

Метод `get_tools()` позволяет динамически настраивать инструменты на основе пользователя:

```python
async def get_tools(
    self,
    user: UserShort | None,
    agent: "BaseAgent",
) -> List[BaseTool]:
    tools = [read_file, list_files]
    
    # Добавить дополнительные инструменты для определенных пользователей
    if user and user.has_premium:
        tools.append(premium_search_tool)
    
    return tools
```

---

## Быстрые ссылки

* Субагенты: [`SUBAGENTS.md`](SUBAGENTS.md)
