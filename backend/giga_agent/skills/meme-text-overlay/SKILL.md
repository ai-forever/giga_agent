---
name: meme-text-overlay
description: Adds meme-style top and bottom text to images using bundled Impact and CJK fonts. Use when overlaying captions on an image, generating meme images, or reproducing the meme_agent text rendering behavior.
---

# Meme Text Overlay

Use this skill when an image needs meme-style captions: white text, black stroke, centered top and bottom placement, automatic wrapping, and CJK-aware font selection.

## Included files

- `scripts/overlay_text.py`: reusable Pillow-based CLI and Python helper.
- `fonts/impact.ttf`: default font for Latin and Cyrillic text.
- `fonts/BlackHanSans-Regular.ttf`: Korean Hangul fallback.
- `fonts/DelaGothicOne-Regular.ttf`: Japanese kana fallback.
- `fonts/ZCOOLQingKeHuangYou-Regular.ttf`: Chinese/CJK fallback.

## Default workflow

1. Use `scripts/overlay_text.py` unless the user specifically needs code integrated elsewhere.
2. Pass the source image, output path, top text, and bottom text.
3. Keep the default maximum output side of `512px`; the script preserves the source image aspect ratio. Use `--preserve-size` only when the user asks to keep original dimensions.

Example:

```bash
python scripts/overlay_text.py input.png output.png \
  --top "TOP TEXT" \
  --bottom "BOTTOM TEXT"
```

Preserve original image dimensions:

```bash
python scripts/overlay_text.py input.png output.png \
  --top "верхний текст" \
  --bottom "нижний текст" \
  --preserve-size
```

## Rendering behavior

- Latin and Cyrillic text is uppercased before wrapping.
- CJK text is wrapped character by character and is not uppercased.
- Font choice is based on all caption text:
  - Hangul: `BlackHanSans-Regular.ttf`
  - Kana: `DelaGothicOne-Regular.ttf`
  - Other CJK: `ZCOOLQingKeHuangYou-Regular.ttf`
  - Non-CJK: `impact.ttf`
- Text is drawn in white with a black stroke.
- Top text starts at `margin_ratio` from the top.
- Bottom text is rendered from the bottom upward.
