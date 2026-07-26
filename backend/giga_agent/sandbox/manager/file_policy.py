"""Единая политика лимитов размера для входящих файлов.

Собрана в одном месте, чтобы каждая входная точка (upload / STT / RAG / skills)
проверяла размер до буферизации тела в RAM, а не изобретала свой порог.
Пороги настраиваются через env; при превышении вызывающий отдаёт HTTP 413.
"""

import os

# Заливка файлов пользователя (POST /files/upload). Тело стримится в бэкенд,
# поэтому лимит защищает backing-хранилище, а не RAM API-процесса.
MAX_UPLOAD_BYTES = int(os.getenv("GIGA_AGENT_MAX_UPLOAD_BYTES", str(500 * 1024 * 1024)))

# Аудио для STT: транскодируется через pydub целиком в RAM, стриминг невозможен,
# поэтому порог здесь строже.
MAX_STT_BYTES = int(os.getenv("GIGA_AGENT_MAX_STT_BYTES", str(25 * 1024 * 1024)))

# Один документ RAG: буферизуется и парсится в RAM целиком.
MAX_RAG_DOC_BYTES = int(
    os.getenv("GIGA_AGENT_MAX_RAG_DOC_BYTES", str(50 * 1024 * 1024))
)

# Архив скилла (POST /skills/upload): читается в RAM целиком и оттуда же
# распаковывается в temp-каталог. Дефолт сохраняет прежний порог, который был
# захардкожен в SkillsService.
MAX_SKILL_ARCHIVE_BYTES = int(
    os.getenv("GIGA_AGENT_MAX_SKILL_ARCHIVE_BYTES", str(10 * 1024 * 1024))
)


class FileTooLargeError(Exception):
    """Заявленный размер файла превышает лимит поверхности.

    Роутит это в HTTP 413. Держим отдельным типом (не HTTPException),
    чтобы политику можно было переиспользовать вне FastAPI-контекста.
    """

    def __init__(self, *, declared_size: int | None, limit: int):
        self.declared_size = declared_size
        self.limit = limit
        size_part = (
            f"{declared_size} байт"
            if declared_size is not None
            else "неизвестного размера"
        )
        super().__init__(f"Файл {size_part} превышает лимит {limit} байт")


def enforce_upload_limit(*, declared_size: int | None, limit: int) -> None:
    """Проверить заявленный размер против лимита.

    :param declared_size: Размер из метаданных запроса (UploadFile.size /
        Content-Length) либо уже посчитанный фактический размер тела. None,
        если размер неизвестен — тогда проверка по метаданным невозможна,
        и защита ложится на стриминговый/bounded приём тела на стороне
        вызывающего.
    :raises FileTooLargeError: Если declared_size известен и больше лимита.
    """
    if declared_size is not None and declared_size > limit:
        raise FileTooLargeError(declared_size=declared_size, limit=limit)
