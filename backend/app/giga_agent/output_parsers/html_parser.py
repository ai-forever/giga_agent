import re
from typing import Any, Optional

from bs4 import BeautifulSoup
from langchain_core.exceptions import OutputParserException
from langchain_core.output_parsers import (
    BaseOutputParser,
)


class HTMLParser(BaseOutputParser):
    tag: Optional[str] = None

    # Функция для извлечения тегов через BeautifulSoup
    def extract_tags(self, content: str) -> Optional[str]:
        soup = BeautifulSoup(content, "html.parser")
        if self.tag:
            # find_all вернет список всех найденных тегов с учетом вложенности
            found_tags = soup.find_all(self.tag.lower())
            if found_tags:
                return "\n".join(str(tag) for tag in found_tags)
        return None

    def parse(self, text: str) -> Any:
        # 1. Если задан тег, пробуем найти его в сыром тексте
        if self.tag:
            result = self.extract_tags(text)
            if result:
                return result

            # 2. Если не нашли, пробуем искать внутри ```html блоков
            markdown_regex = r"```html(.+?)```"
            markdown_matches = re.findall(
                markdown_regex, text, re.DOTALL | re.IGNORECASE
            )
            if markdown_matches:
                inner_content = "\n".join(markdown_matches)
                result_inner = self.extract_tags(inner_content)
                if result_inner:
                    return result_inner

            raise OutputParserException(error=f"Tag <{self.tag}> not found in output!")

        # 3. Если тег не задан — старая логика (возвращаем содержимое ```html блоков)
        regex = r"```html(.+?)```"
        matches = re.findall(regex, text, re.DOTALL | re.IGNORECASE)
        if matches:
            return "\n".join(matches).strip()
        raise OutputParserException(error="No ```html ``` block!")

    @property
    def _type(self) -> str:
        return "html_output_parser"
