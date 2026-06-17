export interface TextSegment {
  type: "text" | "code" | "mermaid";
  content: string;
  lang?: string;
}

export interface ListItem {
  text: string;
  level: number;
  ordered: boolean;
  task?: "todo" | "done";
}

export interface TextBlock {
  type: "heading" | "text" | "table" | "hr" | "list" | "quote";
  level?: number;
  content?: string;
  header?: string[];
  rows?: string[][];
  items?: ListItem[];
}

export interface InlineRun {
  text: string;
  bold?: boolean;
  italic?: boolean;
  code?: boolean;
  strike?: boolean;
  link?: string;
}

export function isMermaidLang(lang?: string): boolean {
  return lang?.toLowerCase() === "mermaid";
}

/**
 * Parses a single line/paragraph of markdown into styled runs.
 * Supports: inline code (`` `x` ``), bold (`**x**` / `__x__`), italic
 * (`*x*` / `_x_`), strikethrough (`~~x~~`), and links (`[text](url)`).
 * Intra-word underscores (e.g. `__init__`) are preserved as literal text.
 */
export function parseInlineRuns(text: string): InlineRun[] {
  const runs: InlineRun[] = [];
  let buffer = "";
  let bold = false;
  let italic = false;
  let strike = false;

  const flush = () => {
    if (!buffer) return;
    const r: InlineRun = { text: buffer };
    if (bold) r.bold = true;
    if (italic) r.italic = true;
    if (strike) r.strike = true;
    runs.push(r);
    buffer = "";
  };

  let i = 0;
  while (i < text.length) {
    const rest = text.slice(i);

    // Inline code (backtick-delimited, no nested formatting inside).
    const codeMatch = rest.match(/^(`+)([\s\S]+?)\1/);
    if (codeMatch) {
      flush();
      const inner = codeMatch[2];
      const r: InlineRun = { text: inner, code: true };
      if (bold) r.bold = true;
      if (italic) r.italic = true;
      if (strike) r.strike = true;
      runs.push(r);
      i += codeMatch[0].length;
      continue;
    }

    // Link `[text](url)` — recurse on inner text for formatting.
    if (rest[0] === "[") {
      const linkMatch = rest.match(
        /^\[([^\]]+)\]\(\s*([^)\s]+)(?:\s+"[^"]*")?\s*\)/,
      );
      if (linkMatch) {
        flush();
        const inner = parseInlineRuns(linkMatch[1]);
        const url = linkMatch[2];
        for (const r of inner) {
          const out: InlineRun = { ...r, link: url };
          if (bold) out.bold = true;
          if (italic) out.italic = true;
          if (strike) out.strike = true;
          runs.push(out);
        }
        i += linkMatch[0].length;
        continue;
      }
    }

    // Strikethrough toggle
    if (rest.startsWith("~~")) {
      flush();
      strike = !strike;
      i += 2;
      continue;
    }

    // Bold toggle
    if (rest.startsWith("**") || rest.startsWith("__")) {
      flush();
      bold = !bold;
      i += 2;
      continue;
    }

    // Italic toggle (single `*` or `_`)
    if (rest[0] === "*" || rest[0] === "_") {
      const ch = rest[0];
      if (ch === "_") {
        const prev = i > 0 ? text[i - 1] : " ";
        const next = i + 1 < text.length ? text[i + 1] : " ";
        if (/\w/.test(prev) && /\w/.test(next)) {
          // intra-word underscore — keep literal
          buffer += ch;
          i++;
          continue;
        }
      }
      flush();
      italic = !italic;
      i++;
      continue;
    }

    buffer += text[i];
    i++;
  }
  flush();
  if (runs.length === 0) runs.push({ text: "" });
  return runs;
}

export function stripMarkdownInline(text: string): string {
  return parseInlineRuns(text)
    .map((r) => r.text)
    .join("");
}

/**
 * If a table cell consists of a single markdown link (`[label](url)`) and
 * nothing else (whitespace allowed around), returns the label and url. Used by
 * exporters to render in-table attachment refs as real hyperlinks instead of
 * stripped text.
 */
export function extractCellSingleLink(
  text: string,
): { label: string; url: string } | null {
  const trimmed = text.trim();
  const m = trimmed.match(/^\[([^\]]+)\]\(\s*([^)\s]+)(?:\s+"[^"]*")?\s*\)$/);
  if (!m) return null;
  return { label: m[1], url: m[2] };
}

export function downshiftHeadings(text: string): string {
  if (!/^#\s+/m.test(text)) return text;
  return text.replace(/^(#{1,5})\s/gm, "$1# ");
}

export function parseTextSegments(text: string): TextSegment[] {
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
    const lang = match[1] || undefined;
    segments.push({
      type: isMermaidLang(lang) ? "mermaid" : "code",
      content: match[2],
      lang,
    });
    lastIdx = match.index + match[0].length;
  }
  if (lastIdx < text.length) {
    segments.push({ type: "text", content: text.slice(lastIdx) });
  }
  return segments;
}

function isHrLine(line: string): boolean {
  return /^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line);
}

function isTableSeparator(line: string): boolean {
  return /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line);
}

function splitTableRow(line: string): string[] {
  const cells = line
    .split(/(?<!\\)\|/)
    .map((c) => c.trim().replace(/\\\|/g, "|"));
  if (cells.length && cells[0] === "") cells.shift();
  if (cells.length && cells[cells.length - 1] === "") cells.pop();
  return cells;
}

function normalizeTable(
  header: string[],
  rows: string[][],
): { header: string[]; rows: string[][] } {
  const cols = Math.max(header.length, ...rows.map((r) => r.length), 1);
  const pad = (r: string[]) => [
    ...r,
    ...Array(Math.max(0, cols - r.length)).fill(""),
  ];
  return { header: pad(header), rows: rows.map(pad) };
}

function parseListLine(line: string): ListItem | null {
  const u = line.match(/^(\s*)[-*+]\s+(.*)$/);
  if (u) {
    let text = u[2];
    let task: "todo" | "done" | undefined;
    const taskMatch = text.match(/^\[([ xX])\]\s+(.*)$/);
    if (taskMatch) {
      task = taskMatch[1] === " " ? "todo" : "done";
      text = taskMatch[2];
    }
    return {
      level: Math.min(Math.floor(u[1].length / 2), 5),
      ordered: false,
      text,
      task,
    };
  }
  const o = line.match(/^(\s*)\d+[.)]\s+(.*)$/);
  if (o) {
    return {
      level: Math.min(Math.floor(o[1].length / 2), 5),
      ordered: true,
      text: o[2],
    };
  }
  return null;
}

function stripQuoteMarker(line: string): string | null {
  const m = line.match(/^\s{0,3}>\s?(.*)$/);
  return m ? m[1] : null;
}

export function parseTextBlocks(text: string): TextBlock[] {
  const blocks: TextBlock[] = [];
  const lines = text.split("\n");
  let buf: string[] = [];

  const flush = () => {
    const content = buf.join("\n").trim();
    if (content) blocks.push({ type: "text", content });
    buf = [];
  };

  let i = 0;
  while (i < lines.length) {
    const line = lines[i];

    const headingMatch = line.match(/^(#{1,6})\s+(.*)/);
    if (headingMatch) {
      flush();
      blocks.push({
        type: "heading",
        level: headingMatch[1].length,
        content: headingMatch[2].trim(),
      });
      i++;
      continue;
    }

    if (!line.includes("|") && isHrLine(line)) {
      flush();
      blocks.push({ type: "hr" });
      i++;
      continue;
    }

    if (line.includes("|") && i + 1 < lines.length) {
      const next = lines[i + 1];
      if (isTableSeparator(next)) {
        flush();
        const header = splitTableRow(line);
        const rows: string[][] = [];
        i += 2;
        while (i < lines.length) {
          const row = lines[i];
          if (!row.trim() || !row.includes("|")) break;
          rows.push(splitTableRow(row));
          i++;
        }
        const norm = normalizeTable(header, rows);
        blocks.push({ type: "table", header: norm.header, rows: norm.rows });
        continue;
      }
    }

    const quoteFirst = stripQuoteMarker(line);
    if (quoteFirst !== null) {
      flush();
      const quoteLines: string[] = [quoteFirst];
      i++;
      while (i < lines.length) {
        const ql = stripQuoteMarker(lines[i]);
        if (ql === null) break;
        quoteLines.push(ql);
        i++;
      }
      blocks.push({ type: "quote", content: quoteLines.join("\n") });
      continue;
    }

    const listFirst = parseListLine(line);
    if (listFirst) {
      flush();
      const items: ListItem[] = [listFirst];
      i++;
      while (i < lines.length) {
        const il = parseListLine(lines[i]);
        if (il) {
          items.push(il);
          i++;
          continue;
        }
        // Continuation: an indented non-empty line (≥1 leading whitespace)
        // that doesn't start a new block becomes part of the previous list
        // item, so wraps stay aligned with the item's text column instead of
        // falling out as a separate paragraph at the list's offsetX.
        const raw = lines[i];
        if (!raw.trim()) break;
        const cont = raw.match(/^\s+(\S.*)$/);
        if (!cont) break;
        if (cont[1].match(/^(#{1,6}\s+|>\s?|\d+[.)]\s+|[-*+]\s+)/)) break;
        if (isHrLine(raw) || isTableSeparator(raw)) break;
        items[items.length - 1].text += " " + cont[1].trim();
        i++;
      }
      blocks.push({ type: "list", items });
      continue;
    }

    buf.push(line);
    i++;
  }
  flush();
  return blocks;
}
