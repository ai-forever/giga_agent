import type { Message } from "@langchain/langgraph-sdk";
import type { FileData } from "@/interfaces";
import { apiClient } from "@/lib/api-client";
import {
  buildContentByPathPreviewUrl,
  buildContentByPathUrl,
  inferAttachmentTypeFromPath,
  isInlineMarkdownAttachmentPath,
  shouldBundleInExport,
} from "@/components/attachments/file-utils";
import { blobToDataUrl, fetchImageAsBlob, measureImageAspect } from "./utils";
import { fetchPlotlyFigure, renderPlotlyToPng } from "./renderers/plotly";
import type {
  Chunk,
  ExportableMessage,
  ExportBundleFile,
  ExportImage,
  InlineMdSection,
  PreparedExport,
  RawAttachment,
} from "./types";

// ---------------------------------------------------------------------------
// Reasoning / artifact text cleaning
// ---------------------------------------------------------------------------

const REASONING_TAGS = ["thinking", "thinkining", "think"] as const;

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
  text = text.replace(/!\[[^\]]*\]\([^)]*\.json\s*\)/gi, "");
  text = text.replace(/\[[^\]]*\.json\]\([^)]*\)/gi, "");
  return text.replace(/\n{3,}/g, "\n\n").trim();
}

// ---------------------------------------------------------------------------
// Message helpers
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

function getHumanDisplayText(message: Message): string {
  const raw =
    (message.additional_kwargs as Record<string, string>)?.user_input ??
    getMessageText(message) ??
    "";
  return raw.replace(/\n*\[system:[\s\S]*$/i, "").trimEnd();
}

// ---------------------------------------------------------------------------
// Attachment resolution
// ---------------------------------------------------------------------------

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
      const { dataUrl, width, height } = await renderPlotlyToPng(figure);
      const res = await fetch(dataUrl);
      const blob = await res.blob();
      let name = att.original_name ?? `plot_${idx}.png`;
      name = name.replace(/\.json$/i, ".png");
      if (!/\.png$/i.test(name)) name += ".png";
      return { name, dataUrl, blob, aspectRatio: height / width };
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
      const aspectRatio = await measureImageAspect(dataUrl);
      return { name, dataUrl, blob, aspectRatio };
    } catch {
      return null;
    }
  }

  return null;
}

async function fetchAttachmentText(path: string): Promise<string> {
  return apiClient.getTextWithRedirectInstruction(
    buildContentByPathPreviewUrl(path),
    { attachAuth: true, credentials: "same-origin", showError: false },
  );
}

/**
 * For an inline-markdown attachment body: find every `attachment:` reference
 * (image or plotly), resolve to an `ExportImage`, and rewrite the markdown
 * so the reference points at the resolved bundled filename. Images of the
 * inline-md document live in `section.images` and are rendered alongside
 * the section body in exporters.
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

  const tableRanges = computeTableLineRanges(body);

  const resolved = await Promise.all(
    matches.map((match) => {
      if (isInsideTable(match.start, tableRanges)) return Promise.resolve(null);
      const path = decodeURI(match.rawPath);
      const fileType = inferAttachmentTypeFromPath(path);
      // plotly: convert to PNG even when authored as a plain link, not `![...]`.
      const isPlotly = fileType === "plotly_graph";
      if ((match.isImage && fileType === "image") || isPlotly) {
        return resolveAttachmentImage(
          { path, file_type: fileType },
          imageCounter.n++,
        );
      }
      return Promise.resolve(null);
    }),
  );

  let out = "";
  let cursor = 0;
  for (let i = 0; i < matches.length; i++) {
    const match = matches[i];
    out += body.slice(cursor, match.start);
    const img = resolved[i];
    if (img) {
      images.push(img);
      out += `![${match.alt || img.name}](${img.name})`;
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

// ---------------------------------------------------------------------------
// Bundle file tracking
// ---------------------------------------------------------------------------

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

interface BundleEntry {
  nameInZip: string;
  blob?: Blob;
}

function pickPngNameHint(alt: string, path: string, fallback: string): string {
  const stripExt = (s: string) =>
    s
      .trim()
      .replace(/\.json$/i, "")
      .replace(/\.plotly$/i, "");
  const a = stripExt(alt ?? "");
  if (a) return `${a}.png`;
  const base = path.split("/").filter(Boolean).pop() ?? "";
  const cleaned = stripExt(base);
  if (cleaned) return `${cleaned}.png`;
  return fallback || "plot.png";
}

function recordBundle(
  path: string,
  hint: string,
  bundleByPath: Map<string, BundleEntry>,
  usedFileNames: Set<string>,
  blob?: Blob,
): string {
  const existing = bundleByPath.get(path);
  if (existing) return existing.nameInZip;
  const cleaned =
    hint.trim() || path.split("/").filter(Boolean).pop() || "file";
  const nameInZip = uniqueBundleFileName(cleaned, usedFileNames);
  bundleByPath.set(path, { nameInZip, blob });
  return nameInZip;
}

// ---------------------------------------------------------------------------
// Table detection
// ---------------------------------------------------------------------------

const PIPE_LINE_RE = /^\s*\|.*\|\s*$/;
const PIPE_SEP_RE = /^\s*\|[\s:|-]+\|\s*$/;

/**
 * Returns half-open `[start, end)` offset ranges in `text` that lie inside a
 * markdown pipe table — a contiguous group of `|...|`-shaped lines that contains
 * at least one separator line (`|---|---|`). Attachment refs whose start offset
 * falls inside such a range must NOT be expanded into image/section chunks:
 * doing so would split the table. They are bundled and rewritten as plain
 * `[label](attachments/name)` links instead.
 */
function computeTableLineRanges(text: string): Array<[number, number]> {
  const lines = text.split("\n");
  const ranges: Array<[number, number]> = [];
  let groupStart = -1;
  let groupOffset = 0;
  let groupHasSep = false;
  let offset = 0;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const lineLen = line.length + 1; // +1 for trailing \n
    if (PIPE_LINE_RE.test(line)) {
      if (groupStart < 0) {
        groupStart = i;
        groupOffset = offset;
        groupHasSep = false;
      }
      if (PIPE_SEP_RE.test(line)) groupHasSep = true;
    } else {
      if (groupStart >= 0 && groupHasSep) {
        ranges.push([groupOffset, offset]);
      }
      groupStart = -1;
      groupHasSep = false;
    }
    offset += lineLen;
  }
  if (groupStart >= 0 && groupHasSep) {
    ranges.push([groupOffset, offset]);
  }
  return ranges;
}

function isInsideTable(pos: number, ranges: Array<[number, number]>): boolean {
  for (const [s, e] of ranges) {
    if (pos >= s && pos < e) return true;
  }
  return false;
}

// ---------------------------------------------------------------------------
// Inline attachment parsing
// ---------------------------------------------------------------------------

/**
 * Matches three forms of `attachment:`-references inside message text:
 *   1. Linked image: `[![alt](attachment:A)](attachment:B)` (captures: 1=alt, 2=A)
 *   2. Plain image: `![alt](attachment:path)` (captures: 3="!", 4=alt, 5=path)
 *   3. Plain link:  `[alt](attachment:path)`  (captures: 3="",  4=alt, 5=path)
 *
 * Linked-image is the first alternative so its inner `![...]` isn't matched
 * separately.
 */
const ATTACHMENT_REF_RE =
  /\[!\[([^\]]*)\]\(\s*<?\s*attachment:([^)>]+?)\s*>?\s*\)\]\(\s*<?\s*attachment:[^)>]+?\s*>?\s*\)|(!?)\[([^\]]*)\]\(\s*<?\s*attachment:([^)>]+?)\s*>?\s*\)/g;

interface AttachmentRef {
  start: number;
  end: number;
  full: string;
  isImage: boolean;
  alt: string;
  path: string;
}

function parseAttachmentRefs(text: string): AttachmentRef[] {
  const refs: AttachmentRef[] = [];
  ATTACHMENT_REF_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = ATTACHMENT_REF_RE.exec(text)) !== null) {
    if (m[2] !== undefined) {
      refs.push({
        start: m.index,
        end: m.index + m[0].length,
        full: m[0],
        isImage: true,
        alt: m[1] ?? "",
        path: decodeURI(m[2].trim()),
      });
    } else {
      refs.push({
        start: m.index,
        end: m.index + m[0].length,
        full: m[0],
        isImage: m[3] === "!",
        alt: m[4] ?? "",
        path: decodeURI(m[5].trim()),
      });
    }
  }
  return refs;
}

interface InlineCtx {
  imageCounter: { n: number };
  bundleByPath: Map<string, BundleEntry>;
  usedFileNames: Set<string>;
}

/**
 * Walks a message text, resolving every inline `attachment:`-reference and
 * emitting an ordered list of `Chunk`s. Text between refs becomes `text`
 * chunks; image/inline-md attachments become their own chunks at the position
 * they appear; bundle refs are folded back into the surrounding text chunk
 * as rewritten `[label](attachments/name)` markdown links.
 */
async function chunkifyText(text: string, ctx: InlineCtx): Promise<Chunk[]> {
  const refs = parseAttachmentRefs(text);
  if (refs.length === 0) {
    return text.trim() ? [{ type: "text", content: text }] : [];
  }

  const tableRanges = computeTableLineRanges(text);

  type Resolved =
    | { kind: "image"; image: ExportImage }
    | { kind: "section"; section: InlineMdSection }
    | { kind: "bundle"; nameInZip: string; alt: string; isImage: boolean }
    | { kind: "keep" };

  const resolved = await Promise.all(
    refs.map(async (ref): Promise<Resolved> => {
      const fileType = inferAttachmentTypeFromPath(ref.path);

      // In-table attachments never render inline (would split the table), but
      // plotly artifacts are still pre-converted to PNG so the bundled file is
      // the rendered image rather than a raw `.plotly.json`. The cell text
      // becomes `[label](attachments/<png>)`.
      if (isInsideTable(ref.start, tableRanges)) {
        if (fileType === "plotly_graph") {
          const image = await resolveAttachmentImage(
            { path: ref.path, file_type: fileType },
            ctx.imageCounter.n++,
          );
          if (image) {
            const hint = pickPngNameHint(ref.alt, ref.path, image.name);
            const nameInZip = recordBundle(
              ref.path,
              hint,
              ctx.bundleByPath,
              ctx.usedFileNames,
              image.blob,
            );
            return { kind: "bundle", nameInZip, alt: ref.alt, isImage: false };
          }
        }
        const nameInZip = recordBundle(
          ref.path,
          ref.alt,
          ctx.bundleByPath,
          ctx.usedFileNames,
        );
        return { kind: "bundle", nameInZip, alt: ref.alt, isImage: false };
      }

      if (fileType === "image" || fileType === "plotly_graph") {
        // plotly artifacts are always rendered to PNG in the export — even
        // when authored as a plain `[label](attachment:foo.plotly.json)` link,
        // the .json itself is never useful in the exported document.
        if (ref.isImage || fileType === "plotly_graph") {
          const image = await resolveAttachmentImage(
            { path: ref.path, file_type: fileType },
            ctx.imageCounter.n++,
          );
          return image ? { kind: "image", image } : { kind: "keep" };
        }
        const nameInZip = recordBundle(
          ref.path,
          ref.alt,
          ctx.bundleByPath,
          ctx.usedFileNames,
        );
        return { kind: "bundle", nameInZip, alt: ref.alt, isImage: false };
      }

      if (fileType === "text" && isInlineMarkdownAttachmentPath(ref.path)) {
        // For text attachments we deliberately drop the alt-text/filename
        // title: the body is shown inline as part of the conversation, and
        // a leading "📄 foo.md" header just adds visual noise. Exporters
        // render only the body + a thin separator when filename is empty.
        const section = await buildInlineMdSection(
          ref.path,
          "",
          ctx.imageCounter,
        );
        return section ? { kind: "section", section } : { kind: "keep" };
      }

      if (shouldBundleInExport(fileType as any, ref.path)) {
        const nameInZip = recordBundle(
          ref.path,
          ref.alt,
          ctx.bundleByPath,
          ctx.usedFileNames,
        );
        return {
          kind: "bundle",
          nameInZip,
          alt: ref.alt,
          isImage: ref.isImage,
        };
      }

      return { kind: "keep" };
    }),
  );

  const chunks: Chunk[] = [];
  let buffer = "";
  const flush = () => {
    if (buffer.trim()) chunks.push({ type: "text", content: buffer });
    buffer = "";
  };

  let cursor = 0;
  for (let i = 0; i < refs.length; i++) {
    const ref = refs[i];
    const r = resolved[i];
    buffer += text.slice(cursor, ref.start);
    if (r.kind === "image") {
      flush();
      chunks.push({ type: "image", image: r.image });
    } else if (r.kind === "section") {
      flush();
      chunks.push({ type: "inlineMd", section: r.section });
    } else if (r.kind === "bundle") {
      const prefix = r.isImage ? "!" : "";
      const label = r.alt || r.nameInZip;
      // encodeURI keeps `/`, encodes spaces and non-ASCII — required so
      // downstream `parseInlineRuns` recognises the URL portion (its link
      // regex disallows whitespace in the target).
      buffer += `${prefix}[${label}](${encodeURI(`attachments/${r.nameInZip}`)})`;
    } else {
      buffer += ref.full;
    }
    cursor = ref.end;
  }
  buffer += text.slice(cursor);
  flush();
  return chunks;
}

// ---------------------------------------------------------------------------
// Human-message file attachments (uploads, not inline markdown refs)
// ---------------------------------------------------------------------------

/**
 * Resolves `additional_kwargs.files` from a human message into a single
 * lightweight `attachmentsList` chunk (mentioned inline as muted text), and
 * registers every file in the bundle so it ends up in `attachments/`.
 *
 * We deliberately don't render uploaded images/md inline for human turns: the
 * user uploaded the files, exporting them as in-document images blows up the
 * chat with the user's own content. A muted "📎 file1.csv, file2.png" line
 * communicates what was attached without dominating the page.
 */
async function chunksFromHumanFiles(
  files: FileData[] | undefined | null,
  ctx: InlineCtx,
): Promise<Chunk[]> {
  if (!files?.length) return [];
  const names: string[] = [];
  for (const f of files) {
    const path = f.path;
    if (!path) continue;
    const hint =
      f.original_name?.trim() ||
      path.split("/").filter(Boolean).pop() ||
      "file";
    const nameInZip = recordBundle(
      path,
      hint,
      ctx.bundleByPath,
      ctx.usedFileNames,
    );
    names.push(nameInZip);
  }
  if (names.length === 0) return [];
  return [{ type: "attachmentsList", names }];
}

// ---------------------------------------------------------------------------
// Main prepare entry point
// ---------------------------------------------------------------------------

export async function prepareMessagesForExport(
  messages: Message[],
): Promise<PreparedExport> {
  const result: ExportableMessage[] = [];
  const ctx: InlineCtx = {
    imageCounter: { n: 0 },
    bundleByPath: new Map<string, BundleEntry>(),
    usedFileNames: new Set<string>(),
  };

  for (const msg of messages) {
    if (msg.type === "tool") {
      // NOTE: tool-message attachment processing is intentionally disabled.
      // Attachments are now sourced exclusively from inline markdown
      // references in human / AI message text (`![alt](attachment:path)`,
      // `[alt](attachment:path)`, or `[![alt](attachment:A)](attachment:B)`).
      // See git history if this needs to be re-enabled.
      continue;
    }

    if (msg.type === "human") {
      const rawText = getHumanDisplayText(msg);
      const textChunks = rawText ? await chunkifyText(rawText, ctx) : [];
      const files = (msg.additional_kwargs as Record<string, unknown>)
        ?.files as FileData[] | undefined;
      const fileChunks = await chunksFromHumanFiles(files, ctx);
      const chunks = [...textChunks, ...fileChunks];
      if (chunks.length === 0) continue;
      result.push({ role: "user", chunks });
      continue;
    }

    if (msg.type === "ai") {
      let text = getMessageText(msg);
      text = stripThinkingBlocks(text);
      const rawChunks = await chunkifyText(text, ctx);
      // Strip leftover `.json` refs from text chunks — the real plotly
      // attachments are already extracted as image chunks by now, so this
      // only kills stray markdown links to raw JSON artifacts.
      const chunks: Chunk[] = [];
      for (const c of rawChunks) {
        if (c.type !== "text") {
          chunks.push(c);
          continue;
        }
        const cleaned = stripJsonArtifactReferences(c.content);
        if (cleaned.trim()) chunks.push({ type: "text", content: cleaned });
      }
      if (chunks.length === 0) continue;
      result.push({ role: "assistant", chunks });
      continue;
    }
  }

  const bundle: ExportBundleFile[] = Array.from(ctx.bundleByPath.entries()).map(
    ([path, entry]) => ({
      path,
      nameInZip: entry.nameInZip,
      blob: entry.blob,
    }),
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
