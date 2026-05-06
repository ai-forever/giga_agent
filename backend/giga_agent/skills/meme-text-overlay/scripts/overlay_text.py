from __future__ import annotations

import argparse
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

FONT_DIR = Path(__file__).resolve().parent.parent / "fonts"


def contains_cjk(text: str) -> bool:
    for ch in text:
        code = ord(ch)
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
        if 0x3040 <= code <= 0x30FF:
            return True
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


def text_size(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    stroke: int,
) -> tuple[int, int]:
    if hasattr(draw, "textbbox"):
        bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]
    return draw.textsize(text, font=font)  # type: ignore[attr-defined]


def wrap_lines(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: int,
    is_cjk: bool,
) -> list[str]:
    if is_cjk:
        lines: list[str] = []
        current = ""
        for ch in text:
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
    lines: list[str] = []
    line: list[str] = []
    for word in words:
        test = " ".join([*line, word])
        if draw.textlength(test, font=font) <= max_width:
            line.append(word)
        else:
            if line:
                lines.append(" ".join(line))
            line = [word]
    if line:
        lines.append(" ".join(line))
    return lines


def try_load_font(paths: list[Path], size: int) -> ImageFont.FreeTypeFont | None:
    for path in paths:
        try:
            return ImageFont.truetype(str(path), size)
        except Exception:
            continue
    return None


def select_font_for_text(
    font_size: int,
    default_font_path: Path,
    sample_text: str,
) -> tuple[ImageFont.FreeTypeFont | ImageFont.ImageFont, bool]:
    is_any_cjk = (
        contains_cjk(sample_text)
        or contains_hangul(sample_text)
        or contains_kana(sample_text)
    )
    if not is_any_cjk:
        try:
            return ImageFont.truetype(str(default_font_path), font_size), False
        except Exception:
            return ImageFont.load_default(), False

    if contains_hangul(sample_text):
        font = try_load_font([FONT_DIR / "BlackHanSans-Regular.ttf"], font_size)
        if font:
            return font, True

    if contains_kana(sample_text):
        font = try_load_font([FONT_DIR / "DelaGothicOne-Regular.ttf"], font_size)
        if font:
            return font, True

    font = try_load_font([FONT_DIR / "ZCOOLQingKeHuangYou-Regular.ttf"], font_size)
    if font:
        return font, True

    try:
        return ImageFont.truetype(str(default_font_path), font_size), True
    except Exception:
        return ImageFont.load_default(), True


def resampling_filter() -> int:
    if hasattr(Image, "Resampling"):
        return Image.Resampling.LANCZOS
    return Image.LANCZOS


def fit_size(size: tuple[int, int], max_size: tuple[int, int]) -> tuple[int, int]:
    width, height = size
    max_width, max_height = max_size
    ratio = min(max_width / width, max_height / height)
    return max(1, round(width * ratio)), max(1, round(height * ratio))


def memeify(
    img_bytes: bytes,
    up_text: str,
    down_text: str,
    font_ratio: float = 0.07,
    stroke: int = 2,
    margin_ratio: float = 0.05,
    output_size: tuple[int, int] | None = (512, 512),
) -> bytes:
    image = ImageOps.exif_transpose(Image.open(BytesIO(img_bytes))).convert("RGB")
    width, height = image.size
    draw = ImageDraw.Draw(image)
    font_size = int(width * font_ratio)
    font, is_cjk = select_font_for_text(
        font_size,
        FONT_DIR / "impact.ttf",
        f"{up_text}\n{down_text}",
    )
    max_width = width - int(width * margin_ratio * 2)

    y = int(height * margin_ratio)
    for line in wrap_lines(draw, up_text, font, max_width, is_cjk):
        line_width, line_height = text_size(draw, line, font=font, stroke=stroke)
        x = (width - line_width) // 2
        draw.text(
            (x, y),
            line,
            font=font,
            fill="white",
            stroke_width=stroke,
            stroke_fill="black",
        )
        y += line_height + 5

    y = height - int(height * margin_ratio)
    for line in wrap_lines(draw, down_text, font, max_width, is_cjk)[::-1]:
        line_width, line_height = text_size(draw, line, font=font, stroke=stroke)
        y -= line_height
        x = (width - line_width) // 2
        draw.text(
            (x, y),
            line,
            font=font,
            fill="white",
            stroke_width=stroke,
            stroke_fill="black",
        )
        y -= 5

    if output_size is not None:
        image = image.resize(fit_size(image.size, output_size), resampling_filter())

    out = BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Add meme-style top and bottom text to an image.",
    )
    parser.add_argument("input", type=Path, help="Input image path")
    parser.add_argument("output", type=Path, help="Output PNG path")
    parser.add_argument("--top", default="", help="Top caption text")
    parser.add_argument("--bottom", default="", help="Bottom caption text")
    parser.add_argument("--font-ratio", type=float, default=0.07)
    parser.add_argument("--stroke", type=int, default=2)
    parser.add_argument("--margin-ratio", type=float, default=0.05)
    parser.add_argument(
        "--output-size",
        type=int,
        default=512,
        help="Maximum output side in pixels. Ignored with --preserve-size.",
    )
    parser.add_argument(
        "--preserve-size",
        action="store_true",
        help="Keep the original image dimensions.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_size = None if args.preserve_size else (args.output_size, args.output_size)
    result = memeify(
        args.input.read_bytes(),
        args.top,
        args.bottom,
        font_ratio=args.font_ratio,
        stroke=args.stroke,
        margin_ratio=args.margin_ratio,
        output_size=output_size,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(result)


if __name__ == "__main__":
    main()
