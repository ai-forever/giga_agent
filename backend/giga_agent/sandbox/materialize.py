"""Общий bounded-materialize для потребителей FileReadResult.

Единственная точка, где ленивый результат чтения (`ContentResult` /
`StreamResult` / `RedirectResult`) превращается в `bytes` с жёстким потолком
и ранним обрывом — чтобы ни один потребитель не буферизовал гигабайты в RAM.
Раньше такая логика была приватной в `modules/io/tools.py` и не
переиспользовалась; остальные потребители (генераторы картинок, телеграм-медиа,
sandbox_api) собирали поток через `b"".join` без лимита.

Поведение при превышении — «мягкое»: возвращаем `(None, too_large=True)`,
а вызывающий сам решает, что показать (обычно понятную ошибку агенту/логу).
"""

import asyncio
from urllib.request import urlopen

from giga_agent.sandbox.base import ContentResult, RedirectResult, StreamResult

_REDIRECT_CHUNK = 1024 * 1024


def metadata_size(result, known_size: int | None = None) -> int | None:
    """Размер файла из метаданных без материализации потока.

    Возвращает None, если размер заранее неизвестен (например, `RedirectResult`
    или `StreamResult` без `content_length`).
    """
    if known_size is not None:
        return known_size
    if isinstance(result, StreamResult):
        return result.content_length
    if isinstance(result, ContentResult):
        return len(result.data)
    return None


async def _download_redirect_bounded(
    url: str, max_bytes: int
) -> tuple[bytes | None, bool]:
    """Скачать по URL с потолком: сначала отсечь по Content-Length, затем читать
    чанками и прерваться, как только буфер превысил max_bytes."""

    def _read() -> tuple[bytes | None, bool]:
        with urlopen(url, timeout=30.0) as response:
            length_raw = response.headers.get("Content-Length")
            if length_raw and length_raw.isdigit() and int(length_raw) > max_bytes:
                return None, True
            buffer = bytearray()
            while True:
                chunk = response.read(_REDIRECT_CHUNK)
                if not chunk:
                    break
                buffer.extend(chunk)
                if len(buffer) > max_bytes:
                    return None, True
            return bytes(buffer), False

    return await asyncio.to_thread(_read)


async def materialize_bounded(result, max_bytes: int) -> tuple[bytes | None, bool]:
    """Материализовать результат чтения в bytes с ранним обрывом на max_bytes.

    Возвращает (data, too_large):
    - (data, False) — контент целиком влез в лимит;
    - (None, True) — контент превысил max_bytes, чтение прервано (поток/загрузка
      не дочитаны — RAM не переполняется);
    - (None, False) — результат недоступен для прямого чтения.
    """
    if isinstance(result, ContentResult):
        if len(result.data) > max_bytes:
            return None, True
        return result.data, False
    if isinstance(result, StreamResult):
        if result.content_length is not None and result.content_length > max_bytes:
            return None, True
        buffer = bytearray()
        async for chunk in result.stream:
            buffer.extend(chunk)
            if len(buffer) > max_bytes:
                return None, True
        return bytes(buffer), False
    if isinstance(result, RedirectResult):
        return await _download_redirect_bounded(result.url, max_bytes)
    return None, False
