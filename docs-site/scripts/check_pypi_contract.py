#!/usr/bin/env python3
"""Проверка соответствия документации опубликованному пакету giga-agent.

Документация в `docs-site/` описывает конкретную версию `giga-agent` из PyPI
(см. `docs-site/docs-version.json`), а не текущий код репозитория, который может
уходить вперёд релиза. Этот скрипт статически (без установки тяжёлых
зависимостей и без импорта пакета) сверяет ключевые утверждения документации
с распакованным wheel этой версии.

Использование:
    python check_pypi_contract.py <путь-к-распакованному-пакету>

где каталог содержит `giga_agent/...`. Скрипт завершается с кодом 1, если
найдено расхождение, и печатает понятный отчёт. Падение в CI означает одно из:
  * документацию пора обновить под новый релиз;
  * в документацию закралась ошибка.

Если меняется само содержимое релиза (например, список модулей в новой версии),
обновите ожидаемый контракт ниже вместе с текстом документации.
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys

# --- Ожидаемый контракт документации для описываемой версии -----------------
# Модули, которые `GigaAgent.get_modules()` регистрирует по умолчанию.
# Должно совпадать с docs-site/docs/developer/modules.md ("загружает N модулей").
EXPECTED_REGISTERED_MODULE_CLASSES = {
    "AuthModule",
    "ReplModule",
    "ImageModule",
    "AnalyzeImagesModule",
    "ScraperModule",
    "SearchModule",
    "RagModule",
    "MemZeroModule",
    "GitHubModule",
    "VKModule",
    "WeatherModule",
    "SubAgentLegacyModule",
}

# Переменные окружения, упомянутые в docs-site/docs/operations/configuration.md.
EXPECTED_ENV_VARS = {
    "GIGA_AGENT_PREFIX_API",
    "GIGA_AGENT_RUNTIME",
    "GIGA_AGENT_SECRET_KEY",
    "GIGA_AGENT_TOOL_MAX_SIZE",
    "GIGA_AGENT_QDRANT_POOL_SIZE",
    "GIGA_AGENT_SCRAPER_TOTAL_CONCURRENCY",
    "GIGA_AGENT_MEM0_QDRANT_ENSURE_CACHE",
    "GIGA_AGENT_LANGGRAPH_DEV_PORT",
}

# Маршрут памяти, упомянутый в architecture.md / modules.md:
# /api/agent/mem_zero_memory/memories
EXPECTED_MEMORY_MODULE_DIR = "modules/mem_zero_memory"
EXPECTED_MEMORY_ROUTE = "/memories"


def fail(errors: list[str]) -> None:
    print("\n❌ Документация расходится с пакетом giga-agent:\n")
    for err in errors:
        print(f"  - {err}")
    print(
        "\nЛибо обновите документацию (и контракт в этом скрипте) под релиз, "
        "либо исправьте ошибку в документации.\n"
    )
    sys.exit(1)


def find_package_root(base: pathlib.Path) -> pathlib.Path:
    """Находит каталог `giga_agent` внутри распакованного пакета."""
    if (base / "giga_agent").is_dir():
        return base / "giga_agent"
    matches = list(base.rglob("giga_agent/__init__.py"))
    if not matches:
        fail([f"не найден каталог giga_agent внутри {base}"])
    return matches[0].parent


def registered_module_classes(pkg: pathlib.Path, errors: list[str]) -> set[str]:
    """Извлекает классы модулей из тела GigaAgent.get_modules() через AST."""
    candidates = list(pkg.rglob("agents/giga_agent.py")) or list(
        pkg.rglob("giga_agent.py")
    )
    source_file = next(
        (c for c in candidates if "class GigaAgent" in c.read_text(encoding="utf-8")),
        None,
    )
    if source_file is None:
        errors.append("не найден файл с классом GigaAgent и методом get_modules()")
        return set()

    tree = ast.parse(source_file.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "get_modules":
            for call in ast.walk(node):
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Name):
                    if call.func.id.endswith("Module"):
                        found.add(call.func.id)
    return found


def main() -> None:
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)

    base = pathlib.Path(sys.argv[1]).resolve()
    pkg = find_package_root(base)
    print(f"Проверяю пакет в {pkg}")

    errors: list[str] = []

    # 1. Список зарегистрированных модулей.
    registered = registered_module_classes(pkg, errors)
    if registered:
        missing = EXPECTED_REGISTERED_MODULE_CLASSES - registered
        extra = registered - EXPECTED_REGISTERED_MODULE_CLASSES
        if missing:
            errors.append(
                "модули, заявленные в документации, но НЕ зарегистрированные в "
                f"пакете: {sorted(missing)}"
            )
        if extra:
            errors.append(
                "модули, зарегистрированные в пакете, но НЕ описанные в "
                f"документации: {sorted(extra)}"
            )
        else:
            print(f"  ✓ зарегистрировано модулей: {len(registered)}")

    # 2. Переменные окружения упоминаются в исходниках пакета.
    all_source = "\n".join(
        p.read_text(encoding="utf-8", errors="ignore") for p in pkg.rglob("*.py")
    )
    for var in sorted(EXPECTED_ENV_VARS):
        if not re.search(rf"\b{re.escape(var)}\b", all_source):
            errors.append(f"переменная окружения из документации не найдена в коде: {var}")
    if not (EXPECTED_ENV_VARS - set(re.findall(r"GIGA_AGENT_[A-Z0-9_]+", all_source))):
        print(f"  ✓ env-переменные найдены: {len(EXPECTED_ENV_VARS)}")

    # 3. Модуль памяти и его маршрут.
    mem_dir = pkg / EXPECTED_MEMORY_MODULE_DIR
    if not mem_dir.is_dir():
        errors.append(
            f"модуль памяти {EXPECTED_MEMORY_MODULE_DIR} не найден "
            "(в документации он называется mem_zero_memory)"
        )
    else:
        api = mem_dir / "api.py"
        if not api.is_file() or EXPECTED_MEMORY_ROUTE not in api.read_text(
            encoding="utf-8"
        ):
            errors.append(
                f"в {EXPECTED_MEMORY_MODULE_DIR}/api.py нет маршрута "
                f"{EXPECTED_MEMORY_ROUTE}, описанного в документации"
            )
        else:
            print(f"  ✓ маршрут памяти {EXPECTED_MEMORY_ROUTE} на месте")

    if errors:
        fail(errors)

    print("\n✅ Документация соответствует опубликованному пакету.\n")


if __name__ == "__main__":
    main()
