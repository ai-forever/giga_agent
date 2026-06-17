import robotoRegularUrl from "@/assets/fonts/Roboto-Regular.ttf";
import robotoBoldUrl from "@/assets/fonts/Roboto-Bold.ttf";
import autoTable from "jspdf-autotable";
import type { InlineRun, TextBlock, TextSegment } from "../markdown-parse";
import {
  downshiftHeadings,
  extractCellSingleLink,
  parseInlineRuns,
  parseTextBlocks,
  parseTextSegments,
  stripMarkdownInline,
} from "../markdown-parse";
import {
  hexToRgb,
  isPythonLang,
  tokenizePythonLine,
} from "../python-highlight";
import {
  detectEmojiSupport,
  hasEmoji,
  renderEmojiToDataUrl,
  splitByEmoji,
} from "../renderers/emoji";
import { fetchLogoPng, LOGO_ASPECT } from "../renderers/logo";
import { renderMermaidToPng } from "../renderers/mermaid";
import type {
  ExportableMessage,
  ExportBundleFile,
  ExportImage,
  InlineMdSection,
} from "../types";

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

export async function exportAsPdf(
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

  // Logo size & layout aligned with docx export:
  // docx uses ~289px @ 96 DPI → ~76mm; padding before the logo matches
  // Word's default header offset (~12mm), and the underline below sits a few
  // mm under the logo, mirroring the docx Header → first content separator.
  const logoWidth = contentWidth * 0.4;
  const logoHeight = logoWidth / LOGO_ASPECT;
  const logoY = 12;

  doc.addImage(logo.dataUrl, "PNG", margin, logoY, logoWidth, logoHeight);
  y = logoY + logoHeight + 8;

  const ensureSpace = (needed: number) => {
    if (y + needed > pageHeight - margin) {
      doc.addPage();
      y = margin;
    }
  };

  const HEADING_SIZES = [16, 14, 12, 11, 10.5, 10];

  const LINK_COLOR: [number, number, number] = [33, 100, 200];

  interface InlineRunOpts {
    fontSize?: number;
    lineH?: number;
    bold?: boolean;
    color?: [number, number, number];
  }

  const applyRunStyle = (run: InlineRun, opts: InlineRunOpts) => {
    const fs = opts.fontSize ?? 10;
    const isBold = (opts.bold ?? false) || !!run.bold;
    if (run.code) {
      doc.setFont("courier", isBold ? "bold" : "normal");
      doc.setFontSize(fs - 0.5);
    } else {
      doc.setFont("Roboto", isBold ? "bold" : "normal");
      doc.setFontSize(fs);
    }
    if (run.link) {
      doc.setTextColor(LINK_COLOR[0], LINK_COLOR[1], LINK_COLOR[2]);
    } else {
      const c = opts.color ?? [0, 0, 0];
      doc.setTextColor(c[0], c[1], c[2]);
    }
  };

  /**
   * Lays out an array of styled runs across one or more lines with word-wrap.
   * Advances `y` past the last line written.
   */
  const renderInlineRunsPdf = (
    runs: InlineRun[],
    baseX: number,
    areaWidth: number,
    opts: InlineRunOpts = {},
  ) => {
    const lineH = opts.lineH ?? 5;

    interface Atom {
      text: string;
      ws: boolean;
      hardBreak: boolean;
      run: InlineRun;
      width: number;
      emojiDataUrl?: string;
    }
    const atoms: Atom[] = [];
    const fsForEmoji = opts.fontSize ?? 10;
    // 1pt ≈ 0.3528 mm; emoji rendered as square glyph at font-size height.
    const emojiSizeMm = fsForEmoji * 0.3528;
    const emojiSupport = detectEmojiSupport();
    for (const run of runs) {
      applyRunStyle(run, opts);
      // Tokenise \n separately from horizontal whitespace, otherwise greedy
      // `\s+` swallows `\n\n` into a single whitespace token and we lose
      // paragraph breaks.
      const tokens = run.text.split(/(\n|[ \t]+)/);
      for (const tok of tokens) {
        if (!tok) continue;
        if (tok === "\n") {
          atoms.push({ text: "", ws: true, hardBreak: true, run, width: 0 });
          continue;
        }
        if (/^\s+$/.test(tok)) {
          atoms.push({
            text: tok,
            ws: true,
            hardBreak: false,
            run,
            width: doc.getTextWidth(tok),
          });
          continue;
        }
        const segs = splitByEmoji(tok);
        if (segs.length === 1 && segs[0].kind === "text") {
          atoms.push({
            text: tok,
            ws: false,
            hardBreak: false,
            run,
            width: doc.getTextWidth(tok),
          });
          continue;
        }
        for (const seg of segs) {
          if (seg.kind === "emoji") {
            if (!emojiSupport) continue;
            const dataUrl = renderEmojiToDataUrl(seg.value);
            if (!dataUrl) continue;
            atoms.push({
              text: "",
              ws: false,
              hardBreak: false,
              run,
              width: emojiSizeMm + 0.4,
              emojiDataUrl: dataUrl,
            });
            continue;
          }
          if (!seg.value) continue;
          atoms.push({
            text: seg.value,
            ws: false,
            hardBreak: false,
            run,
            width: doc.getTextWidth(seg.value),
          });
        }
      }
    }

    let cursorX = baseX;
    let wroteOnLine = false;
    ensureSpace(lineH);

    const newline = () => {
      y += lineH;
      cursorX = baseX;
      wroteOnLine = false;
      ensureSpace(lineH);
    };

    for (const atom of atoms) {
      if (atom.hardBreak) {
        newline();
        continue;
      }
      if (atom.ws) {
        if (!wroteOnLine) continue;
        if (cursorX + atom.width > baseX + areaWidth) {
          newline();
          continue;
        }
        applyRunStyle(atom.run, opts);
        doc.text(atom.text, cursorX, y);
        cursorX += atom.width;
        continue;
      }
      if (cursorX + atom.width > baseX + areaWidth && wroteOnLine) {
        newline();
      }
      if (atom.emojiDataUrl) {
        try {
          doc.addImage(
            atom.emojiDataUrl,
            "PNG",
            cursorX,
            y - emojiSizeMm * 0.85,
            emojiSizeMm,
            emojiSizeMm,
          );
        } catch {
          // skip if jsPDF rejects the image for any reason
        }
        cursorX += atom.width;
        wroteOnLine = true;
        continue;
      }
      applyRunStyle(atom.run, opts);
      doc.text(atom.text, cursorX, y);
      if (atom.run.link) {
        doc.setDrawColor(LINK_COLOR[0], LINK_COLOR[1], LINK_COLOR[2]);
        doc.setLineWidth(0.2);
        doc.line(cursorX, y + 0.6, cursorX + atom.width, y + 0.6);
        const linkH = (opts.fontSize ?? 10) * 0.3528;
        doc.link(cursorX, y - linkH * 0.85, atom.width, linkH, {
          url: atom.run.link,
        });
      }
      if (atom.run.strike) {
        const c = opts.color ?? [0, 0, 0];
        doc.setDrawColor(c[0], c[1], c[2]);
        doc.setLineWidth(0.2);
        doc.line(cursorX, y - 1.2, cursorX + atom.width, y - 1.2);
      }
      cursorX += atom.width;
      wroteOnLine = true;
    }
    if (wroteOnLine) y += lineH;
    doc.setTextColor(0, 0, 0);
    doc.setDrawColor(0, 0, 0);
  };

  /**
   * Draws a code segment of text at (x, baselineY), inlining emoji clusters as
   * PNG images when the OS has an emoji font, or stripping them otherwise.
   * Mirrors the emoji-handling in `renderInlineRunsPdf` but for the direct
   * `doc.text` paths used by code blocks. Returns the advanced X.
   */
  const drawCodeText = (
    text: string,
    x: number,
    baselineY: number,
    fontSizePt: number,
  ): number => {
    const sizeMm = fontSizePt * 0.3528;
    const segs = splitByEmoji(text);
    let cx = x;
    const emojiSupport = detectEmojiSupport();
    for (const seg of segs) {
      if (seg.kind === "emoji") {
        const url = emojiSupport ? renderEmojiToDataUrl(seg.value) : null;
        if (url) {
          try {
            doc.addImage(
              url,
              "PNG",
              cx,
              baselineY - sizeMm * 0.85,
              sizeMm,
              sizeMm,
            );
          } catch {
            // skip if jsPDF rejects the image
          }
          cx += sizeMm + 0.3;
        }
        continue;
      }
      if (!seg.value) continue;
      doc.text(seg.value, cx, baselineY);
      cx += doc.getTextWidth(seg.value);
    }
    return cx;
  };

  const renderCodeBlock = (seg: TextSegment) => {
    const codeIndent = 3;
    const codeLineH = 4;
    const codePad = 2;
    const codeFontPt = 8;
    doc.setFont("Roboto", "normal");
    doc.setFontSize(codeFontPt);
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
          tx = drawCodeText(tok.text, tx, y + 3, codeFontPt);
        }
      } else {
        doc.setTextColor(51, 51, 51);
        drawCodeText(cl, margin + codeIndent, y + 3, codeFontPt);
      }

      y += codeLineH;
    }

    doc.setFillColor(245, 245, 245);
    doc.rect(margin, y, contentWidth, codePad, "F");
    y += codePad + 6;

    doc.setTextColor(0, 0, 0);
  };

  const renderTablePdf = (
    block: TextBlock,
    offsetX: number,
    areaWidth: number,
  ) => {
    if (!block.header || !block.rows) return;
    ensureSpace(10);

    // Pre-resolve per-cell single-link refs so we can paint cells blue and
    // overlay a real PDF link annotation in didDrawCell.
    const cellLinks = new Map<string, string>();
    const cellEmojiLines = new Map<string, string[]>();
    const linkKey = (section: string, rowIdx: number, colIdx: number) =>
      `${section}:${rowIdx}:${colIdx}`;
    const headRow = block.header.map((c, ci) => {
      const lnk = extractCellSingleLink(c);
      if (lnk) {
        cellLinks.set(linkKey("head", 0, ci), lnk.url);
        return lnk.label;
      }
      return stripMarkdownInline(c);
    });
    const bodyRows = block.rows.map((row, ri) =>
      row.map((c, ci) => {
        const lnk = extractCellSingleLink(c);
        if (lnk) {
          cellLinks.set(linkKey("body", ri, ci), lnk.url);
          return lnk.label;
        }
        return stripMarkdownInline(c);
      }),
    );

    autoTable(doc, {
      head: [headRow],
      body: bodyRows,
      startY: y,
      margin: { left: offsetX, right: pageWidth - (offsetX + areaWidth) },
      tableWidth: areaWidth,
      styles: {
        font: "Roboto",
        fontStyle: "normal",
        fontSize: 9,
        cellPadding: 1.8,
        textColor: [51, 51, 51],
        lineColor: [200, 200, 200],
        lineWidth: 0.1,
        overflow: "linebreak",
      },
      headStyles: {
        font: "Roboto",
        fontStyle: "bold",
        fillColor: [235, 235, 245],
        textColor: [0, 0, 0],
      },
      theme: "grid",
      // Per-cell stash for emoji draw: keyed `${section}:${row}:${col}` →
      // wrapped lines that autoTable computed before willDrawCell fired.
      // We re-render them manually in didDrawCell with `drawCodeText`,
      // because autoTable's text renderer can't inline emoji PNGs.
      willDrawCell: (data: any) => {
        const key = linkKey(data.section, data.row.index, data.column.index);
        const url = cellLinks.get(key);
        if (url) {
          data.cell.styles.textColor = [33, 100, 200];
        }
        const rawText: string = Array.isArray(data.cell.text)
          ? data.cell.text.join("\n")
          : String(data.cell.text ?? "");
        if (rawText && hasEmoji(rawText)) {
          const lines = Array.isArray(data.cell.text)
            ? [...data.cell.text]
            : [String(data.cell.text ?? "")];
          cellEmojiLines.set(key, lines);
          // Suppress autoTable's default text rendering for this cell —
          // we'll draw the lines ourselves so each emoji becomes a PNG.
          data.cell.text = [];
        }
      },
      didDrawCell: (data: any) => {
        const key = linkKey(data.section, data.row.index, data.column.index);
        const url = cellLinks.get(key);
        const emojiLines = cellEmojiLines.get(key);
        const cell = data.cell;

        if (emojiLines) {
          // Replicate autoTable's text styling, then draw lines via the
          // emoji-aware helper.
          const styles = cell.styles ?? {};
          const fontSizePt = styles.fontSize ?? 9;
          const fontName = styles.font ?? "Roboto";
          const isBold = styles.fontStyle === "bold";
          doc.setFont(fontName, isBold ? "bold" : "normal");
          doc.setFontSize(fontSizePt);
          const tc = styles.textColor;
          if (Array.isArray(tc) && tc.length >= 3) {
            doc.setTextColor(tc[0], tc[1], tc[2]);
          } else if (typeof tc === "number") {
            doc.setTextColor(tc, tc, tc);
          } else {
            doc.setTextColor(51, 51, 51);
          }
          const padLeft =
            typeof cell.padding === "function" ? cell.padding("left") : 1.8;
          const padTop =
            typeof cell.padding === "function" ? cell.padding("top") : 1.8;
          const lineH = fontSizePt * 0.3528 * 1.15;
          // autoTable default valign: head=middle, body+foot=top.
          const valign =
            styles.valign ?? (data.section === "head" ? "middle" : "top");
          const blockH = lineH * emojiLines.length;
          let baseY: number;
          if (valign === "middle") {
            baseY =
              cell.y + (cell.height - blockH) / 2 + fontSizePt * 0.3528 * 0.85;
          } else if (valign === "bottom") {
            baseY =
              cell.y +
              cell.height -
              padTop -
              blockH +
              fontSizePt * 0.3528 * 0.85;
          } else {
            baseY = cell.y + padTop + fontSizePt * 0.3528 * 0.85;
          }
          for (const line of emojiLines) {
            drawCodeText(line, cell.x + padLeft, baseY, fontSizePt);
            baseY += lineH;
          }
          doc.setTextColor(0, 0, 0);
        }

        if (url) {
          doc.link(cell.x, cell.y, cell.width, cell.height, { url });
        }
      },
    });
    y = (doc as any).lastAutoTable?.finalY ?? y;
    y += 4;
  };

  const renderHrPdf = (offsetX: number, areaWidth: number) => {
    ensureSpace(5);
    y += 1;
    doc.setDrawColor(200, 200, 200);
    doc.line(offsetX, y, offsetX + areaWidth, y);
    y += 4;
  };

  const BULLET_GLYPHS = ["•", "◦", "▪", "▫", "·", "·"];
  const renderListPdf = (
    block: TextBlock,
    offsetX: number,
    areaWidth: number,
    quoteColor?: [number, number, number],
  ) => {
    if (!block.items?.length) return;
    const indentPerLevel = 5;
    const bulletGap = 4;
    const lineH = 5;
    const counters: number[] = [];
    let prevLevel = -1;
    for (const item of block.items) {
      if (item.level < prevLevel) {
        for (let k = item.level + 1; k < counters.length; k++) counters[k] = 0;
      }
      let bullet: string;
      if (item.task === "todo") {
        bullet = "☐";
        counters[item.level] = 0;
      } else if (item.task === "done") {
        bullet = "☑";
        counters[item.level] = 0;
      } else if (item.ordered) {
        counters[item.level] = (counters[item.level] ?? 0) + 1;
        bullet = `${counters[item.level]}.`;
      } else {
        counters[item.level] = 0;
        bullet = BULLET_GLYPHS[Math.min(item.level, BULLET_GLYPHS.length - 1)];
      }
      prevLevel = item.level;

      const bulletX = offsetX + item.level * indentPerLevel;
      const textX = bulletX + bulletGap;
      const textWidth = areaWidth - (textX - offsetX);

      doc.setFont("Roboto", "normal");
      doc.setFontSize(10);
      doc.setTextColor(
        quoteColor?.[0] ?? 0,
        quoteColor?.[1] ?? 0,
        quoteColor?.[2] ?? 0,
      );
      ensureSpace(lineH);
      doc.text(bullet, bulletX, y);

      renderInlineRunsPdf(parseInlineRuns(item.text), textX, textWidth, {
        lineH,
        color: quoteColor,
      });
    }
    y += 1;
  };

  const renderQuotePdf = (
    block: TextBlock,
    offsetX: number,
    areaWidth: number,
  ) => {
    const lineH = 5;
    const innerXPad = 5;
    const innerX = offsetX + innerXPad;
    const innerW = areaWidth - innerXPad - 2;
    const quoteColor: [number, number, number] = [90, 90, 90];
    const innerBlocks = parseTextBlocks(block.content ?? "");

    // Estimate quote height ahead of rendering so we can draw the background
    // fill + left border BEFORE the text (PDF has no z-order, so a rect drawn
    // after text would overwrite it).
    const measureLines = (text: string, w: number, fontSizePt: number) => {
      doc.setFont("Roboto", "normal");
      doc.setFontSize(fontSizePt);
      const lines = doc.splitTextToSize(text, w);
      return Array.isArray(lines) ? lines.length : 1;
    };
    let estH = 0;
    for (const inner of innerBlocks) {
      if (inner.type === "list") {
        estH += (inner.items?.length ?? 0) * lineH;
      } else if (inner.type === "hr") {
        estH += 5;
      } else if (inner.type === "table") {
        estH += 30;
      } else if (inner.type === "heading") {
        estH += lineH * 1.5;
      } else {
        const content = inner.content ?? "";
        if (!content.trim()) {
          estH += 2;
          continue;
        }
        const paragraphs = content.split(/\n{2,}/);
        let lines = 0;
        for (const p of paragraphs) {
          if (!p.trim()) {
            lines += 1;
            continue;
          }
          lines += measureLines(stripMarkdownInline(p), innerW, 10);
        }
        estH += Math.max(lines, 1) * lineH;
      }
    }
    estH = Math.max(estH, lineH);

    const topPad = 1.6;
    const bottomPad = 2;
    const blockH = estH + topPad + bottomPad;

    ensureSpace(blockH + 4);

    const blockTopY = y - lineH * 0.7;

    doc.setFillColor(245, 246, 250);
    doc.rect(offsetX, blockTopY, areaWidth, blockH, "F");
    doc.setFillColor(180, 180, 200);
    doc.rect(offsetX, blockTopY, 0.8, blockH, "F");

    y += topPad;

    for (const inner of innerBlocks) {
      if (inner.type === "list") {
        renderListPdf(inner, innerX, innerW, quoteColor);
      } else if (inner.type === "hr") {
        renderHrPdf(innerX, innerW);
      } else if (inner.type === "table") {
        renderTablePdf(inner, innerX, innerW);
      } else {
        const content = inner.content ?? "";
        if (!content.trim()) {
          y += 2;
          continue;
        }
        renderInlineRunsPdf(parseInlineRuns(content), innerX, innerW, {
          color: quoteColor,
        });
      }
    }
    doc.setTextColor(0, 0, 0);
    y += bottomPad;
  };

  const renderTextBlocks = (text: string) => {
    const blocks = parseTextBlocks(text);
    for (const block of blocks) {
      if (block.type === "heading") {
        const sz = HEADING_SIZES[Math.min((block.level ?? 1) - 1, 5)];
        const lineH = sz * 0.55;
        ensureSpace(lineH + 3);
        y += 2;
        renderInlineRunsPdf(
          parseInlineRuns(block.content ?? ""),
          margin,
          contentWidth,
          { bold: true, fontSize: sz, lineH },
        );
        y += 2;
      } else if (block.type === "table") {
        renderTablePdf(block, margin, contentWidth);
      } else if (block.type === "hr") {
        renderHrPdf(margin, contentWidth);
      } else if (block.type === "list") {
        renderListPdf(block, margin, contentWidth);
      } else if (block.type === "quote") {
        renderQuotePdf(block, margin, contentWidth);
      } else {
        const content = block.content ?? "";
        if (!content.trim()) continue;
        renderInlineRunsPdf(parseInlineRuns(content), margin, contentWidth);
      }
    }
  };

  const renderAttachmentsListPdf = (names: string[]) => {
    if (names.length === 0) return;
    // Tighten the gap to the preceding user heading: the heading's lineH=9
    // followed by the user-message `y += 3` leaves ~8mm of visual whitespace
    // before this muted line, which feels disconnected. Pull up so attachments
    // hug the heading.
    y -= 4;
    const text = `Вложения: ${names.join(", ")}`;
    renderInlineRunsPdf(parseInlineRuns(text), margin, contentWidth, {
      fontSize: 9,
      color: [140, 140, 140],
      lineH: 4.5,
    });
    y += 1;
  };

  const renderImageCentered = (
    img: ExportImage,
    widthRatio: number,
    offsetX = margin,
    areaWidth = contentWidth,
  ) => {
    try {
      const aspect =
        img.aspectRatio && img.aspectRatio > 0 ? img.aspectRatio : 0.55;
      const maxHeight = pageHeight - margin * 2 - 4;
      let imgWidth = areaWidth * widthRatio;
      let imgHeight = imgWidth * aspect;
      if (imgHeight > maxHeight) {
        imgHeight = maxHeight;
        imgWidth = imgHeight / aspect;
      }
      ensureSpace(imgHeight + 5);
      const imgX = offsetX + (areaWidth - imgWidth) / 2;
      doc.addImage(img.dataUrl, "PNG", imgX, y, imgWidth, imgHeight);
      y += imgHeight + 5;
    } catch {
      // skip broken images
    }
  };

  const renderMermaidInPdf = async (
    seg: TextSegment,
    offsetX: number,
    areaWidth: number,
  ) => {
    const result = await renderMermaidToPng(seg.content.trim(), 1600);
    if (!result) {
      renderCodeBlock({ ...seg, type: "code" });
      return;
    }
    // Slight initial shrink (80% of content width) — diagrams look better
    // with some breathing room. Hard-cap height at full page content area so
    // very tall flowcharts can't overflow the page edge; only that cap forces
    // additional shrinking.
    let imgWidth = areaWidth * 0.6;
    let imgHeight = imgWidth * result.aspectRatio;
    const maxHeight = pageHeight - margin * 2 - 4;
    if (imgHeight > maxHeight) {
      imgHeight = maxHeight;
      imgWidth = imgHeight / result.aspectRatio;
    }
    ensureSpace(imgHeight + 8);
    const imgX = offsetX + (areaWidth - imgWidth) / 2;
    doc.addImage(result.dataUrl, "PNG", imgX, y, imgWidth, imgHeight);
    y += imgHeight + 8;
  };

  const renderInlineMdCard = async (section: InlineMdSection) => {
    const inset = 4;
    const innerMargin = margin + inset;
    const innerWidth = contentWidth - inset * 2;
    const startY = y;

    ensureSpace(10);
    y += 2;
    if (section.filename) {
      doc.setFont("Roboto", "bold");
      doc.setFontSize(11);
      doc.setTextColor(60, 60, 60);
      const headerY = y + 4;
      const fsPt = 11;
      const sizeMm = fsPt * 0.3528;
      let tx = innerMargin;
      const segs = splitByEmoji(`📄 ${section.filename}`);
      for (const seg of segs) {
        if (seg.kind === "emoji") {
          const url = detectEmojiSupport()
            ? renderEmojiToDataUrl(seg.value)
            : null;
          if (url) {
            try {
              doc.addImage(
                url,
                "PNG",
                tx,
                headerY - sizeMm * 0.85,
                sizeMm,
                sizeMm,
              );
            } catch {
              // skip on jsPDF error
            }
            tx += sizeMm + 0.6;
          }
          continue;
        }
        doc.text(seg.value, tx, headerY);
        tx += doc.getTextWidth(seg.value);
      }
      y += 7;
    }
    doc.setDrawColor(220, 220, 220);
    doc.line(innerMargin, y, innerMargin + innerWidth, y);
    y += 3;
    doc.setTextColor(0, 0, 0);

    const renderInner = (text: string) => {
      const blocks = parseTextBlocks(text);
      for (const block of blocks) {
        if (block.type === "heading") {
          const sz = HEADING_SIZES[Math.min(block.level ?? 1, 5)];
          const lineH = sz * 0.55;
          ensureSpace(lineH + 3);
          y += 2;
          renderInlineRunsPdf(
            parseInlineRuns(block.content ?? ""),
            innerMargin,
            innerWidth,
            { bold: true, fontSize: sz, lineH },
          );
          y += 2;
        } else if (block.type === "table") {
          renderTablePdf(block, innerMargin, innerWidth);
        } else if (block.type === "hr") {
          renderHrPdf(innerMargin, innerWidth);
        } else if (block.type === "list") {
          renderListPdf(block, innerMargin, innerWidth);
        } else if (block.type === "quote") {
          renderQuotePdf(block, innerMargin, innerWidth);
        } else {
          const content = block.content ?? "";
          if (!content.trim()) continue;
          renderInlineRunsPdf(
            parseInlineRuns(content),
            innerMargin,
            innerWidth,
          );
        }
      }
    };

    const innerSegments = parseTextSegments(downshiftHeadings(section.body));
    for (const seg of innerSegments) {
      if (seg.type === "mermaid") {
        await renderMermaidInPdf(seg, innerMargin, innerWidth);
      } else if (seg.type === "code") {
        renderCodeBlock(seg);
      } else {
        renderInner(seg.content);
      }
    }

    for (const img of section.images) {
      renderImageCentered(img, 0.85, innerMargin, innerWidth);
    }

    y += 2;

    doc.setDrawColor(120, 120, 200);
    doc.setLineWidth(0.6);
    doc.line(margin + 1, startY + 2, margin + 1, y - 1);
    doc.setLineWidth(0.2);
  };

  for (let msgIdx = 0; msgIdx < exportable.length; msgIdx++) {
    const msg = exportable[msgIdx];
    if (msg.role === "user") {
      const headingText = msg.chunks
        .filter((c) => c.type === "text")
        .map((c) => c.content)
        .join(" ")
        .trim();
      if (headingText) {
        ensureSpace(12);
        y += 3;
        renderInlineRunsPdf(
          parseInlineRuns(headingText),
          margin,
          contentWidth,
          { bold: true, fontSize: 16, lineH: 9 },
        );
        y += 3;
      }
      for (const chunk of msg.chunks) {
        if (chunk.type === "image") {
          renderImageCentered(chunk.image, 0.8);
        } else if (chunk.type === "inlineMd") {
          await renderInlineMdCard(chunk.section);
        } else if (chunk.type === "attachmentsList") {
          renderAttachmentsListPdf(chunk.names);
        }
      }
      continue;
    }

    for (const chunk of msg.chunks) {
      if (chunk.type === "inlineMd") {
        await renderInlineMdCard(chunk.section);
        continue;
      }
      if (chunk.type === "image") {
        renderImageCentered(chunk.image, 0.8);
        continue;
      }
      if (chunk.type === "attachmentsList") {
        renderAttachmentsListPdf(chunk.names);
        continue;
      }
      const segments = parseTextSegments(downshiftHeadings(chunk.content));
      for (const seg of segments) {
        if (seg.type === "mermaid")
          await renderMermaidInPdf(seg, margin, contentWidth);
        else if (seg.type === "code") renderCodeBlock(seg);
        else renderTextBlocks(seg.content);
      }
    }
    y += 3;

    // Trailing HR after each AI message acts as a separator. Skip the very
    // last one when nothing follows (no attachments section), so the document
    // ends cleanly instead of with a dangling rule.
    const isLastMsg = msgIdx === exportable.length - 1;
    if (!(isLastMsg && bundle.length === 0)) {
      ensureSpace(3);
      doc.setDrawColor(220, 220, 220);
      doc.line(margin, y, pageWidth - margin, y);
      y += 5;
    }
  }

  if (bundle.length > 0) {
    y += 6;
    ensureSpace(20);
    doc.setFont("Roboto", "bold");
    doc.setFontSize(12);
    doc.setTextColor(0, 0, 0);
    doc.text("Артефакты", margin, y);
    y += 5;

    doc.setFont("Roboto", "normal");
    doc.setFontSize(8);
    doc.setTextColor(140, 140, 140);
    const hint = "В архиве, папка attachments/";
    for (const line of doc.splitTextToSize(hint, contentWidth)) {
      ensureSpace(4);
      doc.text(line, margin, y);
      y += 4;
    }
    y += 2;

    doc.setFont("Roboto", "normal");
    doc.setFontSize(10);
    doc.setTextColor(0, 0, 0);
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
