"""Generate an image with Gemini Nano Banana and save it locally.

Usage:
    uv run python giga_agent/scripts/generate_nano_banana_image.py \
        --prompt "A cyberpunk cat in neon rain"
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable

from google import genai
from google.genai import types

MODEL_NAME = "gemini-2.5-flash-image"
DEFAULT_OUTPUT_DIR = Path("generated_images")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate an image with Gemini Nano Banana (gemini-2.5-flash-image).",
    )
    parser.add_argument(
        "--prompt",
        required=True,
        help="Text prompt for image generation.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output PNG path. Defaults to generated_images/<timestamp>-<slug>.png",
    )
    parser.add_argument(
        "--aspect-ratio",
        choices=["1:1", "3:4", "4:3", "9:16", "16:9"],
        help="Optional output aspect ratio.",
    )
    parser.add_argument(
        "--api-key",
        help="Gemini API key. Defaults to GEMINI_API_KEY from environment.",
    )
    return parser


def _resolve_api_key(cli_value: str | None) -> str:
    api_key = (cli_value or os.getenv("GEMINI_API_KEY", "")).strip()
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set. Export it or pass --api-key.")
    return api_key


def _slugify_prompt(prompt: str, *, max_length: int = 48) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", prompt.lower()).strip("-")
    return slug[:max_length].strip("-") or "image"


def _default_output_path(prompt: str) -> Path:
    timestamp = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    return DEFAULT_OUTPUT_DIR / f"{timestamp}-{_slugify_prompt(prompt)}.png"


def _iter_response_parts(
    response: types.GenerateContentResponse,
) -> Iterable[types.Part]:
    if response.parts:
        return response.parts

    candidates = response.candidates or []
    if candidates and candidates[0].content and candidates[0].content.parts:
        return candidates[0].content.parts

    return []


def generate_image(
    *,
    prompt: str,
    output_path: Path,
    api_key: str,
    aspect_ratio: str | None,
) -> tuple[Path, list[str]]:
    client = genai.Client(api_key=api_key)
    config = None
    if aspect_ratio:
        config = types.GenerateContentConfig(
            image_config=types.ImageConfig(aspect_ratio=aspect_ratio),
        )

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=[prompt],
        config=config,
    )

    text_parts: list[str] = []
    image_saved = False

    for part in _iter_response_parts(response):
        if part.text:
            text_parts.append(part.text.strip())
            continue

        if part.inline_data is None:
            continue

        output_path.parent.mkdir(parents=True, exist_ok=True)
        image = part.as_image()
        image.save(output_path)
        image_saved = True
        break

    if not image_saved:
        raise RuntimeError("Gemini did not return an image for this prompt.")

    return output_path.resolve(), [item for item in text_parts if item]


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    try:
        api_key = _resolve_api_key(args.api_key)
        output_path = args.output or _default_output_path(args.prompt)
        saved_path, text_parts = generate_image(
            prompt=args.prompt,
            output_path=output_path,
            api_key=api_key,
            aspect_ratio=args.aspect_ratio,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if text_parts:
        print("\n".join(text_parts))
    print(saved_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
