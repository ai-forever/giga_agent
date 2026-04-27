import type { Message } from "@langchain/langgraph-sdk";
import { apiClient } from "@/lib/api-client";
import {
  buildContentByPathUrl,
  buildContentByPathPreviewUrl,
  inferAttachmentTypeFromPath,
  isInlineMarkdownAttachmentPath,
  shouldBundleInExport,
} from "@/components/attachments/file-utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ExportImage {
  name: string;
  dataUrl: string;
  blob: Blob;
}

interface InlineMdSection {
  filename: string;
  body: string; // markdown, with attachment image refs replaced by bundled filenames
  images: ExportImage[];
}

interface ExportableMessage {
  role: "user" | "assistant";
  text: string;
  images: ExportImage[];
  inlineMdSections: InlineMdSection[];
}

const INLINE_MD_PLACEHOLDER_RE = /<<<IMD:(\d+)>>>/g;
const inlineMdPlaceholder = (idx: number) => `<<<IMD:${idx}>>>`;

export type ExportFormat = "pdf" | "docx" | "md";

// ---------------------------------------------------------------------------
// Logo (SVG → PNG, loaded lazily once)
// ---------------------------------------------------------------------------

import logoSvgUrl from "@/assets/light_theme_GigaAgent_black-ball.svg";

let _logoPngCache: { blob: Blob; dataUrl: string } | null = null;

const LOGO_CONTENT_VIEWBOX = "200 1250 5000 560";
const LOGO_ASPECT = 5000 / 560;

async function fetchLogoPng(): Promise<{ blob: Blob; dataUrl: string }> {
  if (_logoPngCache) return _logoPngCache;

  const res = await fetch(logoSvgUrl);
  let svgText = await res.text();

  svgText = svgText
    .replace(/viewBox="[^"]*"/, `viewBox="${LOGO_CONTENT_VIEWBOX}"`)
    .replace(/width="[^"]*"/, `width="5000"`)
    .replace(/height="[^"]*"/, `height="560"`);

  const width = 1000;
  const height = Math.round(width / LOGO_ASPECT);
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d")!;

  const svgBlob = new Blob([svgText], {
    type: "image/svg+xml;charset=utf-8",
  });
  const objectUrl = URL.createObjectURL(svgBlob);

  const blob = await new Promise<Blob>((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      ctx.drawImage(img, 0, 0, width, height);
      URL.revokeObjectURL(objectUrl);
      canvas.toBlob(
        (b) => (b ? resolve(b) : reject(new Error("toBlob failed"))),
        "image/png",
      );
    };
    img.onerror = () => {
      URL.revokeObjectURL(objectUrl);
      reject(new Error("Failed to load SVG"));
    };
    img.src = objectUrl;
  });

  const dataUrl = await blobToDataUrl(blob);
  _logoPngCache = { blob, dataUrl };
  return _logoPngCache;
}

async function blobToDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onloadend = () => resolve(reader.result as string);
    reader.readAsDataURL(blob);
  });
}

async function blobToArrayBuffer(blob: Blob): Promise<ArrayBuffer> {
  return blob.arrayBuffer();
}

// ---------------------------------------------------------------------------
// Plotly rendering helpers
// ---------------------------------------------------------------------------

async function getPlotly(): Promise<any> {
  // @ts-ignore — no type declarations for plotly bundle
  const mod = await import("plotly.js/dist/plotly");
  return (mod as any).default ?? mod;
}

async function renderPlotlyToPng(
  figureJson: any,
  width = 900,
  height = 500,
): Promise<string> {
  const Plotly = await getPlotly();
  const container = document.createElement("div");
  container.style.position = "fixed";
  container.style.left = "-9999px";
  container.style.top = "-9999px";
  document.body.appendChild(container);
  try {
    await Plotly.newPlot(
      container,
      figureJson.data,
      {
        ...figureJson.layout,
        template: "plotly_white",
        paper_bgcolor: "#fff",
        plot_bgcolor: "#fff",
        font: { color: "#111" },
        width,
        height,
      },
      { staticPlot: true },
    );
    const dataUrl: string = await Plotly.toImage(container, {
      format: "png",
      width,
      height,
    });
    return dataUrl;
  } finally {
    Plotly.purge(container);
    container.remove();
  }
}

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

async function fetchImageAsBlob(url: string): Promise<Blob> {
  const response = await fetch(url, { credentials: "same-origin" });
  return response.blob();
}

async function fetchPlotlyFigure(path: string): Promise<any> {
  const raw = await apiClient.getTextWithRedirectInstruction(
    buildContentByPathPreviewUrl(path),
    { attachAuth: true, credentials: "same-origin", showError: false },
  );
  return JSON.parse(raw);
}

// ---------------------------------------------------------------------------
// Message filtering & preparation
// ---------------------------------------------------------------------------

function getMessageText(message: Message): string {
  if (Array.isArray(message.content)) {
    return message.content
      .filter((p: any) => p.type === "text")
      .map((p: any) => p.text)
      .join("\n\n");
  }
  return (message.content as string) ?? "";
}

/**
 * Strips model "reasoning" / thinking tags from display and export.
 *
 * Handles:
 *  - well-formed blocks: `<thinking>…</thinking>`, `<thinkining>…</thinkining>` (typo), `<think>…</think>`;
 *  - tags carrying attributes: `<thinking foo="bar">…</thinking>`;
 *  - any case;
 *  - **unclosed** trailing blocks (streaming chunks before the closing tag arrives,
 *    or when the model forgets to close the tag at all).
 */
const REASONING_TAGS = ["thinking", "thinkining", "think"] as const;

export function stripAssistantReasoningTags(text: string): string {
  let out = text;
  for (const tag of REASONING_TAGS) {
    const closed = new RegExp(
      `<${tag}\\b[^>]*>[\\s\\S]*?<\\/${tag}\\s*>`,
      "gi",
    );
    out = out.replace(closed, "");
  }
  for (const tag of REASONING_TAGS) {
    const trailing = new RegExp(`<${tag}\\b[^>]*>[\\s\\S]*$`, "i");
    out = out.replace(trailing, "");
  }
  return out;
}

function stripThinkingBlocks(text: string): string {
  return stripAssistantReasoningTags(text);
}

function stripJsonArtifactReferences(text: string): string {
  // ![alt](…/file.json) or ![alt](…/file.plotly.json)
  text = text.replace(/!\[[^\]]*\]\([^)]*\.json\s*\)/gi, "");
  // [file.json](…) style links to json artifacts
  text = text.replace(/\[[^\]]*\.json\]\([^)]*\)/gi, "");
  return text.replace(/\n{3,}/g, "\n\n").trim();
}

interface TextSegment {
  type: "text" | "code";
  content: string;
  lang?: string;
}

function parseTextSegments(text: string): TextSegment[] {
  const segments: TextSegment[] = [];
  const re = /```(\w*)\n?([\s\S]*?)```/g;
  let lastIdx = 0;
  let match;
  while ((match = re.exec(text)) !== null) {
    if (match.index > lastIdx) {
      segments.push({
        type: "text",
        content: text.slice(lastIdx, match.index),
      });
    }
    segments.push({
      type: "code",
      content: match[2],
      lang: match[1] || undefined,
    });
    lastIdx = match.index + match[0].length;
  }
  if (lastIdx < text.length) {
    segments.push({ type: "text", content: text.slice(lastIdx) });
  }
  return segments;
}

function isPythonLang(lang?: string): boolean {
  if (!lang) return false;
  return /^(?:python|py|python3|py3)$/i.test(lang);
}

// ---------------------------------------------------------------------------
// Python syntax highlighting
// ---------------------------------------------------------------------------

interface CodeToken {
  text: string;
  color: string;
}

const PY_COLORS = {
  keyword: "0000CC",
  builtin: "008080",
  string: "008000",
  comment: "808080",
  number: "B85C00",
  decorator: "AA22FF",
  default: "333333",
};

const PY_KEYWORDS = new Set([
  "False",
  "None",
  "True",
  "and",
  "as",
  "assert",
  "async",
  "await",
  "break",
  "class",
  "continue",
  "def",
  "del",
  "elif",
  "else",
  "except",
  "finally",
  "for",
  "from",
  "global",
  "if",
  "import",
  "in",
  "is",
  "lambda",
  "nonlocal",
  "not",
  "or",
  "pass",
  "raise",
  "return",
  "try",
  "while",
  "with",
  "yield",
]);

const PY_BUILTINS = new Set([
  "print",
  "len",
  "range",
  "int",
  "str",
  "float",
  "list",
  "dict",
  "set",
  "tuple",
  "bool",
  "type",
  "isinstance",
  "enumerate",
  "zip",
  "map",
  "filter",
  "sorted",
  "reversed",
  "open",
  "super",
  "property",
  "staticmethod",
  "classmethod",
  "input",
  "abs",
  "max",
  "min",
  "sum",
  "any",
  "all",
  "hasattr",
  "getattr",
  "setattr",
  "ValueError",
  "TypeError",
  "KeyError",
  "IndexError",
  "Exception",
  "self",
]);

const PY_TOKEN_RE = new RegExp(
  [
    "([fFrRbBuU]{0,2}(?:\"{3}[\\s\\S]*?(?:\"{3}|$)|'{3}[\\s\\S]*?(?:'{3}|$)|\"(?:[^\"\\\\]|\\\\.)*\"|'(?:[^'\\\\]|\\\\.)*'))",
    "(#.*$)",
    "(\\d+(?:\\.\\d+)?(?:[eE][+-]?\\d+)?)",
    "(@\\w+)",
    "(\\w+)",
    "(\\s+)",
    "(.)",
  ].join("|"),
  "gm",
);

function tokenizePythonLine(line: string): CodeToken[] {
  const tokens: CodeToken[] = [];
  PY_TOKEN_RE.lastIndex = 0;
  let m;
  while ((m = PY_TOKEN_RE.exec(line)) !== null) {
    const text = m[0];
    let color = PY_COLORS.default;
    if (m[1]) color = PY_COLORS.string;
    else if (m[2]) color = PY_COLORS.comment;
    else if (m[3]) color = PY_COLORS.number;
    else if (m[4]) color = PY_COLORS.decorator;
    else if (m[5]) {
      if (PY_KEYWORDS.has(text)) color = PY_COLORS.keyword;
      else if (PY_BUILTINS.has(text)) color = PY_COLORS.builtin;
    }
    tokens.push({ text, color });
  }
  return tokens;
}

function hexToRgb(hex: string): [number, number, number] {
  const n = parseInt(hex, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function stripMarkdownInline(text: string): string {
  return text
    .replace(/\*\*(.*?)\*\*/g, "$1")
    .replace(/__(.*?)__/g, "$1")
    .replace(/[*_`#]/g, "");
}

// ---------------------------------------------------------------------------
// Heading helpers
// ---------------------------------------------------------------------------

interface TextBlock {
  type: "heading" | "text";
  level?: number;
  content: string;
}

function parseTextBlocks(text: string): TextBlock[] {
  const blocks: TextBlock[] = [];
  const lines = text.split("\n");
  let buf: string[] = [];

  const flush = () => {
    const content = buf.join("\n").trim();
    if (content) blocks.push({ type: "text", content });
    buf = [];
  };

  for (const line of lines) {
    const m = line.match(/^(#{1,6})\s+(.*)/);
    if (m) {
      flush();
      blocks.push({
        type: "heading",
        level: m[1].length,
        content: m[2].trim(),
      });
    } else {
      buf.push(line);
    }
  }
  flush();
  return blocks;
}

function downshiftHeadings(text: string): string {
  if (!/^#\s+/m.test(text)) return text;
  return text.replace(/^(#{1,5})\s/gm, "$1# ");
}

function getHumanDisplayText(message: Message): string {
  const raw =
    (message.additional_kwargs as Record<string, string>)?.user_input ??
    getMessageText(message) ??
    "";
  return raw.replace(/\n*\[system:[\s\S]*$/i, "").trimEnd();
}

interface RawAttachment {
  path?: string;
  sandbox_path?: string;
  original_name?: string;
  file_type?: string;
}

function collectAttachments(message: Message): RawAttachment[] {
  const kw = message.additional_kwargs as Record<string, any> | undefined;
  if (!kw) return [];
  const files: RawAttachment[] = kw.files ?? [];
  const toolAtts: RawAttachment[] = kw.tool_attachments ?? [];
  return [...files, ...toolAtts];
}

async function resolveAttachmentImage(
  att: RawAttachment,
  idx: number,
): Promise<ExportImage | null> {
  const path = att.sandbox_path ?? att.path;
  if (!path) return null;

  const fileType = att.file_type ?? inferAttachmentTypeFromPath(path);

  if (fileType === "plotly_graph") {
    try {
      const figure = await fetchPlotlyFigure(path);
      const dataUrl = await renderPlotlyToPng(figure);
      const res = await fetch(dataUrl);
      const blob = await res.blob();
      let name = att.original_name ?? `plot_${idx}.png`;
      name = name.replace(/\.json$/i, ".png");
      if (!/\.png$/i.test(name)) name += ".png";
      return { name, dataUrl, blob };
    } catch {
      return null;
    }
  }

  if (fileType === "image") {
    try {
      const url = buildContentByPathUrl(path);
      const blob = await fetchImageAsBlob(url);
      const dataUrl = await blobToDataUrl(blob);
      const name =
        att.original_name ?? path.split("/").pop() ?? `image_${idx}.png`;
      return { name, dataUrl, blob };
    } catch {
      return null;
    }
  }

  return null;
}

async function fetchAttachmentText(path: string): Promise<string> {
  const raw = await apiClient.getTextWithRedirectInstruction(
    buildContentByPathPreviewUrl(path),
    { attachAuth: true, credentials: "same-origin", showError: false },
  );
  return raw;
}

/**
 * For an inline-markdown attachment body: find every `attachment:` reference
 * (image or plotly), resolve to an `ExportImage`, and rewrite the markdown
 * so the reference points at the resolved bundled filename. Non-image
 * attachments referenced from the body are left alone (treated as the
 * surrounding markdown will still link them out).
 */
async function resolveInlineMdImages(
  body: string,
  imageCounter: { n: number },
): Promise<{ body: string; images: ExportImage[] }> {
  const refRe = /(!?)\[([^\]]*)\]\(\s*<?\s*attachment:([^)>]+?)\s*>?\s*\)/g;
  const images: ExportImage[] = [];

  type Match = {
    full: string;
    isImage: boolean;
    alt: string;
    rawPath: string;
    start: number;
    end: number;
  };
  const matches: Match[] = [];
  let m: RegExpExecArray | null;
  while ((m = refRe.exec(body)) !== null) {
    matches.push({
      full: m[0],
      isImage: m[1] === "!",
      alt: m[2],
      rawPath: m[3].trim(),
      start: m.index,
      end: m.index + m[0].length,
    });
  }
  if (matches.length === 0) return { body, images };

  let out = "";
  let cursor = 0;
  for (const match of matches) {
    out += body.slice(cursor, match.start);
    const path = decodeURI(match.rawPath);
    const fileType = inferAttachmentTypeFromPath(path);
    if (
      match.isImage &&
      (fileType === "image" || fileType === "plotly_graph")
    ) {
      const img = await resolveAttachmentImage(
        { path, file_type: fileType },
        imageCounter.n++,
      );
      if (img) {
        images.push(img);
        out += `![${match.alt || img.name}](${img.name})`;
      }
    } else {
      out += match.full;
    }
    cursor = match.end;
  }
  out += body.slice(cursor);
  return { body: out, images };
}

async function buildInlineMdSection(
  path: string,
  title: string,
  imageCounter: { n: number },
): Promise<InlineMdSection | null> {
  try {
    const raw = await fetchAttachmentText(path);
    const { body, images } = await resolveInlineMdImages(raw, imageCounter);
    return { filename: title, body, images };
  } catch {
    return null;
  }
}

function uniqueBundleFileName(suggested: string, used: Set<string>): string {
  const cleaned =
    suggested
      .replace(/[/\\?%*:|"<>]/g, "_")
      .trim()
      .slice(0, 120) || "file";
  if (!used.has(cleaned)) {
    used.add(cleaned);
    return cleaned;
  }
  const dot = cleaned.lastIndexOf(".");
  const base = dot > 0 ? cleaned.slice(0, dot) : cleaned;
  const ext = dot > 0 ? cleaned.slice(dot) : "";
  for (let i = 1; i < 1000; i++) {
    const cand = `${base}_${i}${ext}`;
    if (!used.has(cand)) {
      used.add(cand);
      return cand;
    }
  }
  return `${base}_${Date.now()}${ext}`;
}

function recordBundleIfNeeded(
  path: string,
  att: RawAttachment,
  bundleByPath: Map<string, string>,
  usedFileNames: Set<string>,
) {
  if (bundleByPath.has(path)) return;
  const hint =
    att.original_name?.trim() ||
    path.split("/").filter(Boolean).pop() ||
    "file";
  bundleByPath.set(path, uniqueBundleFileName(hint, usedFileNames));
}

function processAttachmentForQueues(
  att: RawAttachment,
  opts: {
    pendingToolImages: Promise<ExportImage | null>[];
    pendingInlines: { path: string; title: string }[];
    imageCounter: { n: number };
    bundleByPath: Map<string, string>;
    usedFileNames: Set<string>;
  },
) {
  const path = att.sandbox_path ?? att.path;
  if (!path) return;
  const fileType =
    (att.file_type as string) ?? inferAttachmentTypeFromPath(path);

  if (fileType === "plotly_graph" || fileType === "image") {
    opts.pendingToolImages.push(
      resolveAttachmentImage(att, opts.imageCounter.n++),
    );
    return;
  }
  if (fileType === "text" && isInlineMarkdownAttachmentPath(path)) {
    const title =
      att.original_name?.trim() ||
      path.split("/").filter(Boolean).pop() ||
      "file";
    opts.pendingInlines.push({ path, title });
    return;
  }
  if (shouldBundleInExport(fileType as any, path)) {
    recordBundleIfNeeded(path, att, opts.bundleByPath, opts.usedFileNames);
  }
}

function collectBundlesFromMessage(
  message: Message,
  bundleByPath: Map<string, string>,
  usedFileNames: Set<string>,
) {
  for (const att of collectAttachments(message)) {
    const path = att.sandbox_path ?? att.path;
    if (!path) continue;
    const fileType =
      (att.file_type as string) ?? inferAttachmentTypeFromPath(path);
    if (shouldBundleInExport(fileType as any, path)) {
      recordBundleIfNeeded(path, att, bundleByPath, usedFileNames);
    }
  }
}

export interface ExportBundleFile {
  path: string;
  nameInZip: string;
}

export interface PreparedExport {
  exportable: ExportableMessage[];
  bundle: ExportBundleFile[];
}

export async function prepareMessagesForExport(
  messages: Message[],
): Promise<PreparedExport> {
  const result: ExportableMessage[] = [];
  let pendingToolImages: Promise<ExportImage | null>[] = [];
  const pendingInlines: { path: string; title: string }[] = [];
  const imageCounter = { n: 0 };
  const bundleByPath = new Map<string, string>();
  const usedFileNames = new Set<string>();

  const appendInlineSection = (
    row: ExportableMessage,
    section: InlineMdSection,
  ) => {
    const idx = row.inlineMdSections.length;
    row.inlineMdSections.push(section);
    row.text +=
      (row.text.endsWith("\n") ? "" : row.text ? "\n\n" : "") +
      inlineMdPlaceholder(idx);
  };

  const flushPendingInlinesToAssistant = async (row: ExportableMessage) => {
    if (row.role !== "assistant" || pendingInlines.length === 0) return;
    for (const inc of pendingInlines.splice(0, pendingInlines.length)) {
      const section = await buildInlineMdSection(
        inc.path,
        inc.title,
        imageCounter,
      );
      if (section) appendInlineSection(row, section);
    }
  };

  for (const msg of messages) {
    collectBundlesFromMessage(msg, bundleByPath, usedFileNames);

    if (msg.type === "tool") {
      for (const att of collectAttachments(msg)) {
        processAttachmentForQueues(att, {
          pendingToolImages,
          pendingInlines,
          imageCounter,
          bundleByPath,
          usedFileNames,
        });
      }
      continue;
    }

    if (msg.type === "human") {
      if (pendingToolImages.length > 0 && result.length > 0) {
        const prev = result[result.length - 1];
        const resolved = (await Promise.all(pendingToolImages)).filter(
          Boolean,
        ) as ExportImage[];
        prev.images.push(...resolved);
        pendingToolImages = [];
      }
      if (pendingInlines.length > 0 && result.length > 0) {
        const prev = result[result.length - 1];
        if (prev.role === "assistant") {
          await flushPendingInlinesToAssistant(prev);
        } else {
          pendingInlines.length = 0;
        }
      }

      const text = getHumanDisplayText(msg);
      if (!text) continue;
      result.push({ role: "user", text, images: [], inlineMdSections: [] });
      continue;
    }

    if (msg.type === "ai") {
      let text = getMessageText(msg);
      text = stripThinkingBlocks(text);
      text = stripJsonArtifactReferences(text);

      const toolImages = (await Promise.all(pendingToolImages)).filter(
        Boolean,
      ) as ExportImage[];
      pendingToolImages = [];

      const row: ExportableMessage = {
        role: "assistant",
        text,
        images: toolImages,
        inlineMdSections: [],
      };

      for (const inc of pendingInlines.splice(0, pendingInlines.length)) {
        const section = await buildInlineMdSection(
          inc.path,
          inc.title,
          imageCounter,
        );
        if (section) appendInlineSection(row, section);
      }

      const ownAtts = collectAttachments(msg);
      for (const att of ownAtts) {
        const path = att.sandbox_path ?? att.path;
        if (!path) continue;
        const fileType =
          (att.file_type as string) ?? inferAttachmentTypeFromPath(path);
        if (fileType === "plotly_graph" || fileType === "image") {
          const img = await resolveAttachmentImage(att, imageCounter.n++);
          if (img) row.images.push(img);
        } else if (
          fileType === "text" &&
          isInlineMarkdownAttachmentPath(path)
        ) {
          const title =
            att.original_name?.trim() ||
            path.split("/").filter(Boolean).pop() ||
            "file";
          const section = await buildInlineMdSection(path, title, imageCounter);
          if (section) appendInlineSection(row, section);
        } else if (shouldBundleInExport(fileType as any, path)) {
          recordBundleIfNeeded(path, att, bundleByPath, usedFileNames);
        }
      }

      if (
        !row.text.trim() &&
        row.images.length === 0 &&
        row.inlineMdSections.length === 0
      ) {
        continue;
      }

      result.push(row);
      continue;
    }
  }

  if (pendingToolImages.length > 0 && result.length > 0) {
    const prev = result[result.length - 1];
    if (prev.role === "assistant") {
      const resolved = (await Promise.all(pendingToolImages)).filter(
        Boolean,
      ) as ExportImage[];
      prev.images.push(...resolved);
      pendingToolImages = [];
    }
  }
  if (pendingInlines.length > 0 && result.length > 0) {
    const prev = result[result.length - 1];
    await flushPendingInlinesToAssistant(prev);
  }

  const bundle: ExportBundleFile[] = Array.from(bundleByPath.entries()).map(
    ([path, nameInZip]) => ({ path, nameInZip }),
  );

  return { exportable: result, bundle };
}

/**
 * Extract a (human, ai) message pair for a single AI message export.
 * Collects the full span: preceding human message → all intermediate
 * messages (AI tool_calls, tool results with attachments) → the target
 * AI message → any trailing tool messages.
 */
export function extractMessagePair(
  allMessages: Message[],
  aiMessage: Message,
): Message[] {
  const idx = allMessages.findIndex((m) => m.id === aiMessage.id);
  if (idx < 0) return [aiMessage];

  let startIdx = idx;
  for (let i = idx - 1; i >= 0; i--) {
    if (allMessages[i].type === "human") {
      startIdx = i;
      break;
    }
  }

  let endIdx = idx;
  for (let i = idx + 1; i < allMessages.length; i++) {
    if (allMessages[i].type === "tool") {
      endIdx = i;
    } else {
      break;
    }
  }

  return allMessages.slice(startIdx, endIdx + 1);
}

// ---------------------------------------------------------------------------
// Markdown export
// ---------------------------------------------------------------------------

/**
 * Splits an assistant text into ordered chunks of either plain markdown or
 * an `InlineMdSection`. The placeholder `<<<IMD:N>>>` is removed and replaced
 * by the structured section reference.
 */
type AssistantTextChunk =
  | { type: "text"; content: string }
  | { type: "inlineMd"; section: InlineMdSection };

function splitAssistantText(
  text: string,
  sections: InlineMdSection[],
): AssistantTextChunk[] {
  if (sections.length === 0) return [{ type: "text", content: text }];
  const out: AssistantTextChunk[] = [];
  let cursor = 0;
  INLINE_MD_PLACEHOLDER_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = INLINE_MD_PLACEHOLDER_RE.exec(text)) !== null) {
    if (m.index > cursor) {
      const slice = text.slice(cursor, m.index);
      if (slice.trim()) out.push({ type: "text", content: slice });
    }
    const idx = parseInt(m[1], 10);
    const section = sections[idx];
    if (section) out.push({ type: "inlineMd", section });
    cursor = m.index + m[0].length;
  }
  if (cursor < text.length) {
    const tail = text.slice(cursor);
    if (tail.trim()) out.push({ type: "text", content: tail });
  }
  return out;
}

function renderInlineMdAsBlockquote(
  section: InlineMdSection,
  embedImages: boolean,
  imageRefs: ExportImage[],
): string {
  const headerLine = `📄 **${section.filename}**`;
  const bodyText = section.body.trim();
  const bodyLines = bodyText.length ? bodyText.split("\n") : [""];

  const imageBlock: string[] = [];
  for (const img of section.images) {
    if (embedImages) {
      imageBlock.push(`![${img.name}](${img.name})`);
    } else {
      imageBlock.push(`![${img.name}](${img.dataUrl})`);
    }
    imageRefs.push(img);
  }

  const all = [headerLine, "", ...bodyLines];
  if (imageBlock.length) {
    all.push("");
    all.push(...imageBlock);
  }
  return all.map((l) => `> ${l}`).join("\n");
}

function messagesToMarkdown(
  exportable: ExportableMessage[],
  embedImages: boolean,
): { markdown: string; imageRefs: ExportImage[] } {
  const lines: string[] = [];
  const imageRefs: ExportImage[] = [];

  for (const msg of exportable) {
    if (msg.role === "user") {
      lines.push(`# ${msg.text}`);
      lines.push("");
      continue;
    }

    const chunks = splitAssistantText(msg.text, msg.inlineMdSections);
    for (const chunk of chunks) {
      if (chunk.type === "text") {
        lines.push(downshiftHeadings(chunk.content));
        lines.push("");
      } else {
        lines.push(
          renderInlineMdAsBlockquote(chunk.section, embedImages, imageRefs),
        );
        lines.push("");
      }
    }

    for (const img of msg.images) {
      if (embedImages) {
        lines.push(`![${img.name}](${img.name})`);
      } else {
        lines.push(`![${img.name}](${img.dataUrl})`);
      }
      lines.push("");
      imageRefs.push(img);
    }

    lines.push("---");
    lines.push("");
  }

  return { markdown: lines.join("\n"), imageRefs };
}

function appendBundleSectionMarkdown(
  body: string,
  bundle: ExportBundleFile[],
): string {
  if (bundle.length === 0) return body;
  const list = bundle
    .map((f) => `- [\`${f.nameInZip}\`](attachments/${f.nameInZip})`)
    .join("\n");
  return body.trimEnd() + "\n\n## Прикреплённые файлы\n\n" + list + "\n";
}

async function exportAsMarkdown(
  exportable: ExportableMessage[],
  title: string,
  bundle: ExportBundleFile[],
): Promise<Blob> {
  const hasExportImages = exportable.some(
    (m) =>
      m.images.length > 0 ||
      m.inlineMdSections.some((s) => s.images.length > 0),
  );
  if (!hasExportImages && bundle.length === 0) {
    const { markdown } = messagesToMarkdown(exportable, false);
    return new Blob([markdown], { type: "text/markdown" });
  }

  const { markdown, imageRefs } = messagesToMarkdown(
    exportable,
    hasExportImages,
  );
  const withBundle = appendBundleSectionMarkdown(markdown, bundle);
  const JSZip = (await import("jszip")).default;
  const zip = new JSZip();
  zip.file(`${title}.md`, withBundle);
  for (const img of imageRefs) {
    zip.file(img.name, img.blob);
  }
  for (const f of bundle) {
    const blob = await fetchImageAsBlob(buildContentByPathUrl(f.path));
    zip.file(`attachments/${f.nameInZip}`, blob);
  }
  return zip.generateAsync({ type: "blob" });
}

// ---------------------------------------------------------------------------
// PDF export (embeds Roboto TTF for Cyrillic support)
// ---------------------------------------------------------------------------

import robotoRegularUrl from "@/assets/fonts/Roboto-Regular.ttf";
import robotoBoldUrl from "@/assets/fonts/Roboto-Bold.ttf";

let _fontCacheRegular: string | null = null;
let _fontCacheBold: string | null = null;

async function fetchFontBase64(url: string): Promise<string> {
  const res = await fetch(url);
  const buf = await res.arrayBuffer();
  const bytes = new Uint8Array(buf);
  let binary = "";
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

async function loadPdfFonts(): Promise<{
  regular: string;
  bold: string;
}> {
  if (!_fontCacheRegular) {
    _fontCacheRegular = await fetchFontBase64(robotoRegularUrl);
  }
  if (!_fontCacheBold) {
    _fontCacheBold = await fetchFontBase64(robotoBoldUrl);
  }
  return { regular: _fontCacheRegular, bold: _fontCacheBold };
}

async function exportAsPdf(
  exportable: ExportableMessage[],
  _title: string,
  bundle: ExportBundleFile[] = [],
): Promise<Blob> {
  const { jsPDF } = await import("jspdf");
  const doc = new jsPDF({ orientation: "portrait", unit: "mm", format: "a4" });
  const pageWidth = doc.internal.pageSize.getWidth();
  const pageHeight = doc.internal.pageSize.getHeight();
  const margin = 15;
  const contentWidth = pageWidth - margin * 2;
  let y = margin;

  const fonts = await loadPdfFonts();
  doc.addFileToVFS("Roboto-Regular.ttf", fonts.regular);
  doc.addFileToVFS("Roboto-Bold.ttf", fonts.bold);
  doc.addFont("Roboto-Regular.ttf", "Roboto", "normal");
  doc.addFont("Roboto-Bold.ttf", "Roboto", "bold");

  const logo = await fetchLogoPng();

  const logoWidth = contentWidth * 0.525;
  const logoHeight = logoWidth / LOGO_ASPECT;

  // First-page header: logo left-aligned + separator line
  doc.addImage(logo.dataUrl, "PNG", margin, 5, logoWidth, logoHeight);
  const lineY = 5 + logoHeight + 2;
  doc.setDrawColor(200, 200, 200);
  doc.line(margin, lineY, pageWidth - margin, lineY);
  y = lineY + 5;

  const ensureSpace = (needed: number) => {
    if (y + needed > pageHeight - margin) {
      doc.addPage();
      y = margin;
    }
  };

  const HEADING_SIZES = [16, 14, 12, 11, 10.5, 10];

  const renderCodeBlock = (seg: TextSegment) => {
    const codeIndent = 3;
    const codeLineH = 4;
    const codePad = 2;
    doc.setFont("Roboto", "normal");
    doc.setFontSize(8);
    const python = isPythonLang(seg.lang);
    const codeLines = seg.content.trim().split("\n");

    ensureSpace(codeLineH + codePad);
    doc.setFillColor(245, 245, 245);
    doc.rect(margin, y, contentWidth, codePad, "F");
    y += codePad;

    for (const cl of codeLines) {
      ensureSpace(codeLineH + 1);
      doc.setFillColor(245, 245, 245);
      doc.rect(margin, y, contentWidth, codeLineH, "F");

      if (python) {
        const tokens = tokenizePythonLine(cl);
        let tx = margin + codeIndent;
        for (const tok of tokens) {
          const [r, g, b] = hexToRgb(tok.color);
          doc.setTextColor(r, g, b);
          doc.text(tok.text, tx, y + 3);
          tx += doc.getTextWidth(tok.text);
        }
      } else {
        doc.setTextColor(51, 51, 51);
        doc.text(cl, margin + codeIndent, y + 3);
      }

      y += codeLineH;
    }

    doc.setFillColor(245, 245, 245);
    doc.rect(margin, y, contentWidth, codePad, "F");
    y += codePad + 2;

    doc.setTextColor(0, 0, 0);
  };

  const renderTextBlocks = (text: string) => {
    const blocks = parseTextBlocks(text);
    for (const block of blocks) {
      if (block.type === "heading") {
        const sz = HEADING_SIZES[Math.min(block.level! - 1, 5)];
        const lineH = sz * 0.55;
        ensureSpace(lineH + 3);
        y += 2;
        doc.setFont("Roboto", "bold");
        doc.setFontSize(sz);
        const wrapped = doc.splitTextToSize(
          stripMarkdownInline(block.content),
          contentWidth,
        );
        for (const wl of wrapped) {
          ensureSpace(lineH);
          doc.text(wl, margin, y);
          y += lineH;
        }
        y += 2;
      } else {
        const clean = stripMarkdownInline(block.content);
        if (!clean.trim()) continue;
        doc.setFont("Roboto", "normal");
        doc.setFontSize(10);
        const textLines = doc.splitTextToSize(clean, contentWidth);
        for (const tl of textLines) {
          ensureSpace(5);
          doc.text(tl, margin, y);
          y += 5;
        }
      }
    }
  };

  for (const msg of exportable) {
    if (msg.role === "user") {
      ensureSpace(12);
      y += 3;
      doc.setFont("Roboto", "bold");
      doc.setFontSize(16);
      const wrapped = doc.splitTextToSize(
        stripMarkdownInline(msg.text),
        contentWidth,
      );
      for (const wl of wrapped) {
        ensureSpace(9);
        doc.text(wl, margin, y);
        y += 9;
      }
      y += 3;
      continue;
    }

    const renderImageCentered = (
      img: ExportImage,
      widthRatio: number,
      offsetX = margin,
      areaWidth = contentWidth,
    ) => {
      try {
        const imgWidth = areaWidth * widthRatio;
        const imgHeight = imgWidth * 0.55;
        ensureSpace(imgHeight + 5);
        const imgX = offsetX + (areaWidth - imgWidth) / 2;
        doc.addImage(img.dataUrl, "PNG", imgX, y, imgWidth, imgHeight);
        y += imgHeight + 5;
      } catch {
        // skip broken images
      }
    };

    const renderInlineMdCard = (section: InlineMdSection) => {
      const inset = 4;
      const innerMargin = margin + inset;
      const innerWidth = contentWidth - inset * 2;
      const startY = y;

      ensureSpace(10);
      y += 2;
      doc.setFont("Roboto", "bold");
      doc.setFontSize(11);
      doc.setTextColor(60, 60, 60);
      doc.text(`📄 ${section.filename}`, innerMargin, y + 4);
      y += 7;
      doc.setDrawColor(220, 220, 220);
      doc.line(innerMargin, y, innerMargin + innerWidth, y);
      y += 3;
      doc.setTextColor(0, 0, 0);

      const renderInner = (text: string) => {
        const blocks = parseTextBlocks(text);
        for (const block of blocks) {
          if (block.type === "heading") {
            // Downshift inside a card so the body heading never matches outer H1.
            const sz = HEADING_SIZES[Math.min(block.level ?? 1, 5)];
            const lineH = sz * 0.55;
            ensureSpace(lineH + 3);
            y += 2;
            doc.setFont("Roboto", "bold");
            doc.setFontSize(sz);
            const wrapped = doc.splitTextToSize(
              stripMarkdownInline(block.content),
              innerWidth,
            );
            for (const wl of wrapped) {
              ensureSpace(lineH);
              doc.text(wl, innerMargin, y);
              y += lineH;
            }
            y += 2;
          } else {
            const clean = stripMarkdownInline(block.content);
            if (!clean.trim()) continue;
            doc.setFont("Roboto", "normal");
            doc.setFontSize(10);
            for (const tl of doc.splitTextToSize(clean, innerWidth)) {
              ensureSpace(5);
              doc.text(tl, innerMargin, y);
              y += 5;
            }
          }
        }
      };

      const innerSegments = parseTextSegments(downshiftHeadings(section.body));
      for (const seg of innerSegments) {
        if (seg.type === "code") {
          renderCodeBlock(seg);
        } else {
          renderInner(seg.content);
        }
      }

      for (const img of section.images) {
        renderImageCentered(img, 0.85, innerMargin, innerWidth);
      }

      y += 2;

      // Left vertical bar spanning the card content (best-effort, single-page only).
      doc.setDrawColor(120, 120, 200);
      doc.setLineWidth(0.6);
      doc.line(margin + 1, startY + 2, margin + 1, y - 1);
      doc.setLineWidth(0.2);
    };

    const shifted = downshiftHeadings(msg.text);
    const chunks = splitAssistantText(shifted, msg.inlineMdSections);
    for (const chunk of chunks) {
      if (chunk.type === "inlineMd") {
        renderInlineMdCard(chunk.section);
        continue;
      }
      const segments = parseTextSegments(chunk.content);
      for (const seg of segments) {
        if (seg.type === "code") renderCodeBlock(seg);
        else renderTextBlocks(seg.content);
      }
    }
    y += 3;

    for (const img of msg.images) {
      renderImageCentered(img, 0.8);
    }

    ensureSpace(3);
    doc.setDrawColor(220, 220, 220);
    doc.line(margin, y, pageWidth - margin, y);
    y += 5;
  }

  if (bundle.length > 0) {
    y += 6;
    ensureSpace(20);
    doc.setFont("Roboto", "bold");
    doc.setFontSize(12);
    const head = "Прикреплённые файлы (в архиве, папка attachments/)";
    for (const line of doc.splitTextToSize(head, contentWidth)) {
      ensureSpace(6);
      doc.text(line, margin, y);
      y += 6;
    }
    y += 2;
    doc.setFont("Roboto", "normal");
    doc.setFontSize(10);
    for (const f of bundle) {
      for (const line of doc.splitTextToSize(
        `• ${f.nameInZip}`,
        contentWidth,
      )) {
        ensureSpace(5);
        doc.text(line, margin, y);
        y += 5;
      }
    }
  }

  return doc.output("blob");
}

// ---------------------------------------------------------------------------
// DOCX export
// ---------------------------------------------------------------------------

async function exportAsDocx(
  exportable: ExportableMessage[],
  _title: string,
  bundle: ExportBundleFile[] = [],
): Promise<Blob> {
  const docxModule = await import("docx");
  const {
    Document,
    Packer,
    Paragraph,
    TextRun,
    ImageRun,
    Header,
    HeadingLevel,
    AlignmentType,
    BorderStyle,
    ShadingType,
  } = docxModule;

  const logo = await fetchLogoPng();
  const logoBuffer = await blobToArrayBuffer(logo.blob);

  const docxLogoWidth = Math.round(550 * 0.525);
  const logoImage = new ImageRun({
    data: logoBuffer,
    transformation: {
      width: docxLogoWidth,
      height: Math.round(docxLogoWidth / LOGO_ASPECT),
    },
    type: "png",
  });

  const DOCX_HEADING_MAP: Record<
    number,
    (typeof HeadingLevel)[keyof typeof HeadingLevel]
  > = {
    1: HeadingLevel.HEADING_1,
    2: HeadingLevel.HEADING_2,
    3: HeadingLevel.HEADING_3,
    4: HeadingLevel.HEADING_4,
    5: HeadingLevel.HEADING_5,
    6: HeadingLevel.HEADING_6,
  };

  const children: any[] = [];

  const pushCodeBlock = (seg: TextSegment) => {
    const python = isPythonLang(seg.lang);
    const codeLines = seg.content.trim().split("\n");
    for (const cl of codeLines) {
      const runs = python
        ? tokenizePythonLine(cl).map(
            (tok) =>
              new TextRun({
                text: tok.text,
                font: "Courier New",
                size: 18,
                color: tok.color,
              }),
          )
        : [
            new TextRun({
              text: cl || " ",
              font: "Courier New",
              size: 18,
              color: PY_COLORS.default,
            }),
          ];
      if (runs.length === 0) {
        runs.push(new TextRun({ text: " ", font: "Courier New", size: 18 }));
      }
      children.push(
        new Paragraph({
          children: runs,
          shading: { type: ShadingType.CLEAR, fill: "F5F5F5" },
          spacing: { after: 0, line: 276 },
        }),
      );
    }
    children.push(new Paragraph({ spacing: { after: 80 } }));
  };

  const pushTextBlocks = (text: string) => {
    const blocks = parseTextBlocks(text);
    for (const block of blocks) {
      if (block.type === "heading") {
        const lvl = Math.min(block.level!, 6);
        children.push(
          new Paragraph({
            text: stripMarkdownInline(block.content),
            heading: DOCX_HEADING_MAP[lvl] ?? HeadingLevel.HEADING_6,
            spacing: { before: 200, after: 120 },
          }),
        );
      } else {
        const clean = stripMarkdownInline(block.content);
        const paras = clean.split(/\n{2,}/);
        for (const para of paras) {
          if (!para.trim()) continue;
          children.push(
            new Paragraph({
              children: [
                new TextRun({ text: para.trim(), size: 24, font: "Roboto" }),
              ],
              spacing: { after: 80 },
            }),
          );
        }
      }
    }
  };

  for (const msg of exportable) {
    if (msg.role === "user") {
      children.push(
        new Paragraph({
          children: [
            new TextRun({
              text: stripMarkdownInline(msg.text),
              font: "Roboto",
              size: 36,
              bold: true,
              color: "000000",
            }),
          ],
          heading: HeadingLevel.HEADING_1,
          spacing: { before: 360, after: 200 },
        }),
      );
      continue;
    }

    const cardBorder = {
      top: { style: BorderStyle.SINGLE, size: 4, color: "BFBFE8" },
      bottom: { style: BorderStyle.SINGLE, size: 4, color: "BFBFE8" },
      left: { style: BorderStyle.SINGLE, size: 12, color: "7D7DCC" },
      right: { style: BorderStyle.SINGLE, size: 4, color: "BFBFE8" },
    } as const;
    const cardShading = {
      type: ShadingType.CLEAR,
      fill: "F6F7FB",
    } as const;

    const pushInlineMdCard = async (section: InlineMdSection) => {
      children.push(
        new Paragraph({
          children: [
            new TextRun({
              text: `📄 ${section.filename}`,
              size: 24,
              bold: true,
              font: "Roboto",
              color: "333333",
            }),
          ],
          spacing: { before: 200, after: 80 },
          border: cardBorder,
          shading: cardShading,
          indent: { left: 200 },
        }),
      );

      const downshifted = downshiftHeadings(section.body);
      const innerSegments = parseTextSegments(downshifted);
      for (const seg of innerSegments) {
        if (seg.type === "code") {
          pushCodeBlock(seg);
          continue;
        }
        const blocks = parseTextBlocks(seg.content);
        for (const block of blocks) {
          if (block.type === "heading") {
            const lvl = Math.min((block.level ?? 1) + 1, 6);
            children.push(
              new Paragraph({
                children: [
                  new TextRun({
                    text: stripMarkdownInline(block.content),
                    size: 22,
                    bold: true,
                    font: "Roboto",
                  }),
                ],
                heading: DOCX_HEADING_MAP[lvl] ?? HeadingLevel.HEADING_6,
                spacing: { before: 120, after: 60 },
                border: cardBorder,
                shading: cardShading,
                indent: { left: 200 },
              }),
            );
          } else {
            const clean = stripMarkdownInline(block.content);
            for (const para of clean.split(/\n{2,}/)) {
              if (!para.trim()) continue;
              children.push(
                new Paragraph({
                  children: [
                    new TextRun({
                      text: para.trim(),
                      size: 22,
                      font: "Roboto",
                    }),
                  ],
                  spacing: { after: 60 },
                  border: cardBorder,
                  shading: cardShading,
                  indent: { left: 200 },
                }),
              );
            }
          }
        }
      }

      for (const img of section.images) {
        try {
          const imgBuffer = await blobToArrayBuffer(img.blob);
          children.push(
            new Paragraph({
              children: [
                new ImageRun({
                  data: imgBuffer,
                  transformation: { width: 460, height: 260 },
                  type: "png",
                }),
              ],
              spacing: { before: 80, after: 80 },
              alignment: AlignmentType.CENTER,
              border: cardBorder,
              shading: cardShading,
              indent: { left: 200 },
            }),
          );
        } catch {
          // skip
        }
      }
    };

    const shifted = downshiftHeadings(msg.text);
    const chunks = splitAssistantText(shifted, msg.inlineMdSections);
    for (const chunk of chunks) {
      if (chunk.type === "inlineMd") {
        await pushInlineMdCard(chunk.section);
        continue;
      }
      const segments = parseTextSegments(chunk.content);
      for (const seg of segments) {
        if (seg.type === "code") {
          pushCodeBlock(seg);
        } else {
          pushTextBlocks(seg.content);
        }
      }
    }

    for (const img of msg.images) {
      try {
        const imgBuffer = await blobToArrayBuffer(img.blob);
        children.push(
          new Paragraph({
            children: [
              new ImageRun({
                data: imgBuffer,
                transformation: { width: 500, height: 280 },
                type: "png",
              }),
            ],
            spacing: { before: 120, after: 120 },
            alignment: AlignmentType.CENTER,
          }),
        );
      } catch {
        // skip broken images
      }
    }

    children.push(
      new Paragraph({
        border: {
          bottom: {
            style: BorderStyle.SINGLE,
            size: 1,
            color: "CCCCCC",
          },
        },
        spacing: { after: 200 },
      }),
    );
  }

  if (bundle.length > 0) {
    children.push(
      new Paragraph({
        children: [
          new TextRun({
            text: "Прикреплённые файлы (в архиве, папка attachments/)",
            size: 24,
            font: "Roboto",
            bold: true,
          }),
        ],
        spacing: { before: 240, after: 120 },
      }),
    );
    for (const f of bundle) {
      children.push(
        new Paragraph({
          children: [
            new TextRun({
              text: `• ${f.nameInZip}`,
              size: 22,
              font: "Roboto",
            }),
          ],
          spacing: { after: 60 },
        }),
      );
    }
  }

  const doc = new Document({
    sections: [
      {
        properties: { titlePage: true },
        headers: {
          first: new Header({
            children: [
              new Paragraph({
                children: [logoImage],
                alignment: AlignmentType.LEFT,
              }),
            ],
          }),
        },
        children,
      },
    ],
  });

  return Packer.toBlob(doc);
}

// ---------------------------------------------------------------------------
// Download helper
// ---------------------------------------------------------------------------

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

async function downloadZippedFileWithAttachments(
  mainFileName: string,
  mainBlob: Blob,
  bundle: ExportBundleFile[],
): Promise<void> {
  const JSZip = (await import("jszip")).default;
  const zip = new JSZip();
  zip.file(mainFileName, mainBlob);
  for (const f of bundle) {
    const blob = await fetchImageAsBlob(buildContentByPathUrl(f.path));
    zip.file(`attachments/${f.nameInZip}`, blob);
  }
  const out = await zip.generateAsync({ type: "blob" });
  const zipName =
    mainFileName.replace(/\.(md|docx|pdf|zip)$/i, ".zip") || "export.zip";
  const safeZipName = zipName.endsWith(".zip") ? zipName : `${zipName}.zip`;
  downloadBlob(out, safeZipName);
}

export async function exportChat(
  messages: Message[],
  format: ExportFormat,
  title: string,
): Promise<void> {
  const safeTitle = title.replace(/[/\\?%*:|"<>]/g, "_").slice(0, 80) || "chat";
  const { exportable, bundle: bundleList } =
    await prepareMessagesForExport(messages);
  const hasBundle = bundleList.length > 0;

  if (format === "md") {
    const out = await exportAsMarkdown(exportable, safeTitle, bundleList);
    if (out.type === "text/markdown" && !hasBundle) {
      downloadBlob(out, `${safeTitle}.md`);
    } else {
      downloadBlob(out, `${safeTitle}.zip`);
    }
    return;
  }

  if (format === "pdf") {
    const blob = await exportAsPdf(exportable, safeTitle, bundleList);
    if (hasBundle) {
      return downloadZippedFileWithAttachments(
        `${safeTitle}.pdf`,
        blob,
        bundleList,
      );
    }
    return downloadBlob(blob, `${safeTitle}.pdf`);
  }

  if (format === "docx") {
    const blob = await exportAsDocx(exportable, safeTitle, bundleList);
    if (hasBundle) {
      return downloadZippedFileWithAttachments(
        `${safeTitle}.docx`,
        blob,
        bundleList,
      );
    }
    return downloadBlob(blob, `${safeTitle}.docx`);
  }
}
