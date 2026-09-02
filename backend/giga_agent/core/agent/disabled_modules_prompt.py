"""System-prompt section describing modules the user has toggled off.

Отключённые пользователем модули (``disabled_modules``) не байндят свои тулы и
не добавляют инструкции. Но модель полезно знать, что такие возможности
*существуют*, но выключены, — чтобы вместо неудачной попытки выполнить действие
она могла подсказать пользователю включить нужный модуль и что для этого нужно
(какие креды/интеграции подключить).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from giga_agent.core.module import BaseModule


def _connect_hint(module: "BaseModule") -> str:
    """Короткая подсказка «что нужно, чтобы подключить модуль».

    Собирается из объявленных модулем секретов (``get_secrets``) и интеграций
    (``get_providers``). Best-effort: любые ошибки построения игнорируются, чтобы
    один сбойный модуль не ломал весь системный промпт.
    """
    parts: list[str] = []

    try:
        for secret in module.get_secrets():
            name = (secret.get("name") or "").strip()
            if not name:
                continue
            desc = (secret.get("description") or "").strip()
            parts.append(f"{name} — {desc}" if desc else name)
    except Exception:  # noqa: BLE001 — подсказка не должна ломать промпт
        pass

    try:
        for provider in module.get_providers():
            label = (getattr(provider, "label", "") or "").strip()
            if label:
                parts.append(f"интеграция «{label}»")
    except Exception:  # noqa: BLE001 — подсказка не должна ломать промпт
        pass

    return "; ".join(parts)


def build_disabled_modules_prompt(modules: "list[BaseModule]") -> str | None:
    """Render the «Отключённые модули» block, or ``None`` if there are none.

    *modules* — уже отфильтрованный список пользовательских (``label`` непустой)
    модулей, отключённых через ``disabled_modules``.
    """
    lines: list[str] = []
    for module in modules:
        label = (module.label or "").strip()
        if not label:
            continue
        description = (module.description or "").strip()
        head = f"- {label}"
        if description:
            head = f"{head}: {description}"
        hint = _connect_hint(module)
        if hint:
            head = f"{head} Чтобы подключить, нужно: {hint}."
        lines.append(head)

    if not lines:
        return None

    listing = "\n".join(lines)
    return (
        "Отключённые модули (сейчас НЕДОСТУПНЫ — их инструменты выключены "
        "пользователем):\n"
        f"{listing}\n"
        "Не пытайся выполнять действия этих модулей — их инструментов нет. "
        "Если задача пользователя требует одного из них, сообщи, что нужно "
        "включить соответствующий модуль в настройках, и подскажи, что для "
        "этого нужно подключить."
    )
