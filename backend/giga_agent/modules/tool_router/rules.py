"""Правила маршрутизации тулов для GigaChat (бюджет блока функций ~4096 токенов).

Роутер подбирает релевантный поднабор тулов под каждый вызов модели, опираясь
на ключевые слова в разговоре. Подход детерминированный (без LLM-вызовов).
"""

from __future__ import annotations

from dataclasses import dataclass

# Тулы, которые НИКОГДА не выкидываются:
# think / multi_tool_use — спец-тулы GigaChat (размышление и параллельный вызов),
# request_tools — escape-hatch (см. tools.py), которым модель «дозапрашивает» набор.
CORE_TOOL_NAMES: frozenset[str] = frozenset(
    {"think", "multi_tool_use", "request_tools"}
)


@dataclass(frozen=True)
class ToolsetRule:
    name: str
    keywords: tuple[str, ...]
    # Имена тулов или префиксы (с завершающим "_") этого тулсета.
    tools: tuple[str, ...]


# Порядок важен: правила проверяются сверху вниз, совпавшие тулсеты приоритетны.
RULES: tuple[ToolsetRule, ...] = (
    ToolsetRule(
        name="yandex_disk",
        keywords=("диск", "яндекс.диск", "yandex", "файл", "папк", "директор",
                  "выгруз", "загруз", "скачай", "залей"),
        tools=("disk_",),
    ),
    ToolsetRule(
        name="yandex_tracker",
        keywords=("трекер", "tracker", "задач", "тикет", "issue", "очеред",
                  "спринт", "доск"),
        tools=("tracker_",),
    ),
    ToolsetRule(
        name="yandex_mail",
        keywords=("почт", "письм", "mail", "inbox", "входящ", "отправ письмо",
                  "напиши на", "ящик"),
        tools=("mail_",),
    ),
    ToolsetRule(
        name="mock_tracker",
        keywords=("демо-трекер", "демо трекер", "demo", "мок-трекер", "demo-"),
        tools=("mock_",),
    ),
    ToolsetRule(
        name="code",
        keywords=("код", "посчита", "график", "выполни", "python", "скрипт",
                  "проанализир", "таблиц", "excel", "csv", "датафрейм"),
        tools=("python", "shell", "await_shell", "read_file", "write_file",
               "edit_file", "delete_file"),
    ),
    ToolsetRule(
        name="web",
        keywords=("сайт", "ссылк", "url", "страниц", "в интернете", "загугли"),
        tools=("get_urls",),
    ),
    ToolsetRule(
        name="docs",
        keywords=("документ", "знани", "rag", "из файлов знаний"),
        tools=("get_documents",),
    ),
    ToolsetRule(
        name="memory",
        keywords=("запомни", "вспомни", "память", "помнишь"),
        tools=("search_memories",),
    ),
    ToolsetRule(
        name="images",
        keywords=("картинк", "изображен", "фото", "скриншот"),
        tools=("analyze_image",),
    ),
    ToolsetRule(
        name="skills",
        keywords=("скилл", "навык", "skill"),
        tools=("read_skill_manifest",),
    ),
)

# Точечные ключевые слова под КОНКРЕТНЫЕ операции — поднимают нужный тул в
# приоритет внутри домена. Решает кейс «удали» → disk_delete, когда на ход
# влезает лишь ~3 disk-тула и без этого нужный тул выпадал.
TOOL_KEYWORDS: dict[str, tuple[str, ...]] = {
    "disk_delete": ("удали", "удал", "снеси", "корзин", "delete", "remove"),
    "disk_create_folder": ("папк", "директор", "каталог", "mkdir"),
    "disk_upload_text": ("создай файл", "загруз", "сохрани", "запиш", "выгруз",
                         "upload"),
    "disk_read_text": ("прочит", "содержим", "открой файл", "read", "скачай"),
    "disk_publish": ("публич", "ссылк", "поделись", "share", "опубликуй"),
    "disk_list_files": ("список", "покажи файл", "листинг", "что в папк"),
    # --- Яндекс.Трекер ---
    "tracker_create_issue": ("создай задач", "заведи задач", "новая задач",
                             "новую задач", "создать тикет", "заведи тикет"),
    "tracker_search_issues": ("найди задач", "поиск задач", "какие задач",
                              "список задач", "мои задач", "найти тикет"),
    "tracker_get_issue": ("покажи задач", "детали задач", "карточк задач",
                          "открой задач", "что по задач"),
    "tracker_add_comment": ("комментар", "коммент", "напиши в задач",
                            "добавь коммент"),
    "tracker_update_issue": ("обнови задач", "измени задач", "поменяй задач",
                             "переименуй задач"),
    "tracker_transition": ("переведи задач", "закрой задач", "статус задач",
                           "в работу", "верни в", "в готово", "выполнен"),
    "tracker_board": ("сгруппир", "по исполнител", "по статус", "по приоритет",
                      "разбей задач", "доск", "группиров", "канбан"),
    # --- Яндекс.Почта ---
    "mail_search": ("письма", "входящ", "проверь почт", "что в почт", "inbox",
                    "последние письм", "новые письм"),
    "mail_read": ("прочит письмо", "открой письмо", "что в письме", "содержим письма"),
    "mail_send": ("отправь письмо", "напиши письмо", "напиши на", "отправ почт",
                  "ответь на письмо"),
    # --- Демо-трекер (мок, шаг 3) ---
    "mock_search_issues": ("демо-трекер", "демо трекер", "mock", "mock_search",
                           "demo-трекер", "задачи demo"),
    "mock_get_issue": ("задачу demo", "тикет demo", "demo-задач", "карточк demo"),
    "mock_board": ("сгруппир демо", "демо доск", "demo board", "демо-доск"),
}

# Приоритет дозаполнения, когда ничего конкретного не совпало (бюджет-гард всё
# равно держит общий рабочий набор). Чем раньше в списке — тем выше приоритет.
DEFAULT_PRIORITY: tuple[str, ...] = (
    "disk_", "tracker_", "mail_", "python", "shell", "get_urls",
    "get_documents", "analyze_image", "search_memories", "read_skill_manifest",
)


def matches(text: str, rule: ToolsetRule) -> bool:
    return any(kw in text for kw in rule.keywords)
