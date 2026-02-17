import base64
import os
from io import BytesIO

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.runnables import (
    RunnableConfig,
    RunnableParallel,
    RunnablePassthrough,
)
from PIL import Image, ImageDraw, ImageFont

from giga_agent.modules.subagents_legacy.agents.meme_agent.config import MemeState, llm
from giga_agent.modules.subagents_legacy.agents.meme_agent.prompts.ru import (
    IMAGE_PROMPT,
)

__location__ = os.path.realpath(os.path.join(os.getcwd(), os.path.dirname(__file__)))

from giga_agent.generators.image import load_image_gen
from giga_agent.utils.jupyter import REPLUploader, RunUploadFile


def memeify(
    img_bytes: bytes,
    up_text: str,
    down_text: str,
    font_path: str = "impact.ttf",  # путь к шрифту Impact
    font_ratio: float = 0.07,  # высота текста ≈ 10 % от ширины картинки
    stroke: int = 2,  # толщина обводки
    margin_ratio: float = 0.05,  # поля сверху/снизу
) -> bytes:
    """Наносит up_text и down_text на картинку, возвращает bytes."""

    def text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont):
        """Возвращает (w, h) c учётом версии Pillow."""
        if hasattr(draw, "textbbox"):  # Pillow ≥ 8.0, в т.ч. ≥10
            bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke)
            return bbox[2] - bbox[0], bbox[3] - bbox[1]
        # старые Pillow
        return draw.textsize(text, font=font)  # type: ignore[attr-defined]

    def contains_cjk(text: str) -> bool:
        """Грубая проверка наличия CJK/корейских/японских символов."""
        for ch in text:
            code = ord(ch)
            # CJK Unified Ideographs and Extensions
            if (
                0x3400 <= code <= 0x4DBF
                or 0x4E00 <= code <= 0x9FFF
                or 0xF900 <= code <= 0xFAFF
                or 0x20000 <= code <= 0x2A6DF
                or 0x2A700 <= code <= 0x2B73F
                or 0x2B740 <= code <= 0x2B81F
                or 0x2B820 <= code <= 0x2CEAF
                or 0x2CEB0 <= code <= 0x2EBEF
            ):
                return True
            # Hiragana, Katakana
            if 0x3040 <= code <= 0x30FF:
                return True
            # Hangul
            if 0xAC00 <= code <= 0xD7AF:
                return True
        return False

    def contains_hangul(text: str) -> bool:
        for ch in text:
            code = ord(ch)
            if (
                0xAC00 <= code <= 0xD7AF
                or 0x1100 <= code <= 0x11FF
                or 0x3130 <= code <= 0x318F
                or 0xA960 <= code <= 0xA97F
                or 0xD7B0 <= code <= 0xD7FF
            ):
                return True
        return False

    def contains_kana(text: str) -> bool:
        for ch in text:
            code = ord(ch)
            if 0x3040 <= code <= 0x30FF or 0x31F0 <= code <= 0x31FF:
                return True
        return False

    def wrap_lines(draw, text, font, max_width, is_cjk: bool):
        """Разбивает текст на строки так, чтобы каждая влезла в max_width.
        Для CJK (без пробелов) переносим по символам, не upper().
        """
        if is_cjk:
            raw = text
            lines = []
            current = ""
            for ch in raw:
                test = current + ch
                if draw.textlength(test, font=font) <= max_width:
                    current = test
                else:
                    if current:
                        lines.append(current)
                    current = ch
            if current:
                lines.append(current)
            return lines
        words = text.upper().split()
        lines, line = [], []
        for word in words:
            test = " ".join(line + [word])
            if draw.textlength(test, font=font) <= max_width:
                line.append(word)
            else:
                if line:
                    lines.append(" ".join(line))
                line = [word]
        if line:
            lines.append(" ".join(line))
        return lines

    def try_load_font(paths, size: int):
        for p in paths:
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
        return None

    def select_font_for_text(font_size: int, default_font_path: str, sample_text: str):
        """Выбирает шрифт из локальной папки.
        - Латиница/кириллица/без CJK → Impact (default_font_path)
        - Корейский (есть хангыль) → BlackHanSans-Regular.ttf
        - Японский (есть каны) → DelaGothicOne-Regular.ttf
        - Китайский (CJK без кан/хангыля) → ZCOOLQingKeHuangYou-Regular.ttf
        """
        is_any_cjk = (
            contains_cjk(sample_text)
            or contains_hangul(sample_text)
            or contains_kana(sample_text)
        )
        if not is_any_cjk:
            try:
                return (
                    ImageFont.truetype(
                        os.path.join(__location__, default_font_path),
                        font_size,
                    ),
                    False,
                )
            except Exception:
                return ImageFont.load_default(), False

        # Приоритет: KR → JP → CN
        if contains_hangul(sample_text):
            font = try_load_font(
                [os.path.join(__location__, "BlackHanSans-Regular.ttf")],
                font_size,
            )
            if font:
                return font, True
        if contains_kana(sample_text):
            font = try_load_font(
                [os.path.join(__location__, "DelaGothicOne-Regular.ttf")],
                font_size,
            )
            if font:
                return font, True

        # Китайский по умолчанию для прочих CJK
        font = try_load_font(
            [os.path.join(__location__, "ZCOOLQingKeHuangYou-Regular.ttf")],
            font_size,
        )
        if font:
            return font, True

        # Если вдруг локальные файлы отсутствуют, последний шанс — Impact или default
        try:
            return (
                ImageFont.truetype(
                    os.path.join(__location__, default_font_path),
                    font_size,
                ),
                True,
            )
        except Exception:
            return ImageFont.load_default(), True

    # открываем картинку
    im = Image.open(BytesIO(img_bytes)).convert("RGB")
    w, h = im.size
    draw = ImageDraw.Draw(im)

    # подбираем размер шрифта из ширины картинки
    font_size = int(w * font_ratio)

    # Выбор шрифта с учётом возможного CJK
    font, is_cjk = select_font_for_text(
        font_size,
        "impact.ttf",
        f"{up_text}\n{down_text}",
    )

    max_width = w - int(w * margin_ratio * 2)

    # --- верхний текст ---
    top_lines = wrap_lines(draw, up_text, font, max_width, is_cjk)
    y = int(h * margin_ratio)
    for line in top_lines:
        line_w, line_h = text_size(draw, line, font=font)
        x = (w - line_w) // 2
        # чёрный контур
        draw.text(
            (x, y),
            line,
            font=font,
            fill="white",
            stroke_width=stroke,
            stroke_fill="black",
        )
        y += line_h + 5  # небольшой интервал между строками

    # --- нижний текст ---
    bottom_lines = wrap_lines(draw, down_text, font, max_width, is_cjk)[
        ::-1
    ]  # рисуем снизу вверх
    y = h - int(h * margin_ratio)
    for line in bottom_lines:
        line_w, line_h = text_size(draw, line, font=font)
        y -= line_h
        x = (w - line_w) // 2
        draw.text(
            (x, y),
            line,
            font=font,
            fill="white",
            stroke_width=stroke,
            stroke_fill="black",
        )
        y -= 5

    # сохраняем в bytes
    out = BytesIO()
    im = im.resize((512, 512), Image.Resampling.LANCZOS)
    im.save(out, format="PNG")
    return out.getvalue()


img_ch = (
    IMAGE_PROMPT
    | llm
    | RunnableParallel({"message": RunnablePassthrough(), "json": JsonOutputParser()})
).with_retry()


async def image_node(state: MemeState, config: RunnableConfig):
    resp = await img_ch.ainvoke(
        {
            "messages": [
                (
                    "user",
                    f"Идея пользователя: '{state['task']}'\n"
                    + state["messages"][-1].content,
                ),
            ],
        },
    )
    if config["configurable"].get("print_messages", False):
        resp["message"].pretty_print()
    image_gen = load_image_gen()
    await image_gen.init()
    image_data = await image_gen.generate_image(
        resp["json"]["image"]["description"],
        1024,
        1024,
    )
    image_data = memeify(
        base64.b64decode(image_data),
        state["meme_idea"]["up_text"],
        state["meme_idea"]["down_text"],
        stroke=6,
    )

    uploader = REPLUploader()
    upload_files = [
        RunUploadFile(
            path="meme.jpg",
            file_type="image",
            content=image_data,
        ),
    ]
    upload_resp = await uploader.upload_run_files(
        upload_files,
        config["configurable"]["thread_id"],
    )
    uploaded = upload_resp[0]

    return {"meme_image": uploaded}
