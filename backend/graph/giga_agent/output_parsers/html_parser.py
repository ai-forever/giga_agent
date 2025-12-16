import re
from typing import Any

from langchain_core.exceptions import OutputParserException
from langchain_core.output_parsers import (
    BaseOutputParser,
)


class HTMLParser(BaseOutputParser):
    def parse(self, text: str) -> Any:
        regex = r"```html(.+?)```"
        matches = re.findall(regex, text, re.DOTALL)
        if matches:
            if len(matches) > 1:
                raise OutputParserException(error="Too many ```html ``` !")
            return "\n".join(matches).strip()
        raise OutputParserException(error="No ```html ``` block!")

    @property
    def _type(self) -> str:
        return "html_output_parser"
