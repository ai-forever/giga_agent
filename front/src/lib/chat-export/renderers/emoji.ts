/**
 * Renders emoji to PNG via canvas using the system emoji font stack, so PDFs
 * (which only have Roboto embedded and can't read system fonts) can still show
 * emojis. If the OS has no emoji font, `detectEmojiSupport` returns false and
 * callers strip emoji instead of rendering tofu.
 */

const EMOJI_FONT_STACK =
  '"Apple Color Emoji","Segoe UI Emoji","Segoe UI Symbol",' +
  '"Noto Color Emoji","Twemoji Mozilla","EmojiOne Color","Android Emoji",sans-serif';

const EMOJI_RE_GLOBAL =
  /\p{Extended_Pictographic}(?:\u{FE0F}|\u{200D}\p{Extended_Pictographic})*/gu;
const EMOJI_RE_SINGLE =
  /\p{Extended_Pictographic}(?:\u{FE0F}|\u{200D}\p{Extended_Pictographic})*/u;

let _support: boolean | null = null;
const _pngCache = new Map<string, string>();

export function hasEmoji(text: string): boolean {
  return EMOJI_RE_SINGLE.test(text);
}

export function stripEmoji(text: string): string {
  return text.replace(EMOJI_RE_GLOBAL, "");
}

/**
 * Probes the browser/OS for emoji rendering: paints a known emoji on canvas
 * with the system emoji font stack and counts non-transparent pixels. The
 * threshold catches both "no font" (transparent) and "tofu" (small filled
 * rectangle) cases reasonably well.
 */
export function detectEmojiSupport(): boolean {
  if (_support !== null) return _support;
  if (typeof document === "undefined") return (_support = false);
  try {
    const size = 32;
    const canvas = document.createElement("canvas");
    canvas.width = size;
    canvas.height = size;
    const ctx = canvas.getContext("2d");
    if (!ctx) return (_support = false);
    ctx.font = `24px ${EMOJI_FONT_STACK}`;
    ctx.textBaseline = "top";
    ctx.fillText("📄", 0, 0); // 📄
    const data = ctx.getImageData(0, 0, size, size).data;
    let painted = 0;
    for (let i = 3; i < data.length; i += 4) if (data[i] > 0) painted++;
    return (_support = painted > 40);
  } catch {
    return (_support = false);
  }
}

export function renderEmojiToDataUrl(emoji: string): string | null {
  if (!detectEmojiSupport()) return null;
  const cached = _pngCache.get(emoji);
  if (cached) return cached;
  try {
    const size = 64;
    const canvas = document.createElement("canvas");
    canvas.width = size;
    canvas.height = size;
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    ctx.font = `${Math.floor(size * 0.82)}px ${EMOJI_FONT_STACK}`;
    ctx.textBaseline = "middle";
    ctx.textAlign = "center";
    ctx.fillText(emoji, size / 2, size / 2 + 2);
    const dataUrl = canvas.toDataURL("image/png");
    _pngCache.set(emoji, dataUrl);
    return dataUrl;
  } catch {
    return null;
  }
}

export function splitByEmoji(
  text: string,
): Array<{ kind: "text" | "emoji"; value: string }> {
  if (!text) return [];
  const parts: Array<{ kind: "text" | "emoji"; value: string }> = [];
  let last = 0;
  for (const m of text.matchAll(EMOJI_RE_GLOBAL)) {
    const idx = m.index ?? 0;
    if (idx > last) parts.push({ kind: "text", value: text.slice(last, idx) });
    parts.push({ kind: "emoji", value: m[0] });
    last = idx + m[0].length;
  }
  if (last < text.length) {
    parts.push({ kind: "text", value: text.slice(last) });
  }
  return parts;
}
