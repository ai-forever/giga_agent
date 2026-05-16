import {
  downshiftHeadings,
  extractCellSingleLink,
  parseInlineRuns,
  parseTextBlocks,
  parseTextSegments,
  stripMarkdownInline,
} from "../markdown-parse";
import type { InlineRun, TextBlock, TextSegment } from "../markdown-parse";
import {
  PY_COLORS,
  isPythonLang,
  tokenizePythonLine,
} from "../python-highlight";
import { LOGO_ASPECT, fetchLogoPng } from "../renderers/logo";
import { renderMermaidToPng } from "../renderers/mermaid";
import { blobToArrayBuffer } from "../utils";
import type {
  ExportableMessage,
  ExportBundleFile,
  ExportImage,
  InlineMdSection,
} from "../types";

function safeDecode(uri: string): string {
  try {
    return decodeURI(uri);
  } catch {
    return uri;
  }
}

export async function exportAsDocx(
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
    Table,
    TableRow,
    TableCell,
    WidthType,
    ExternalHyperlink,
  } = docxModule;

  interface InlineDocxOpts {
    size?: number;
    font?: string;
    color?: string;
    bold?: boolean;
    italics?: boolean;
  }

  const inlineRunsToDocx = (
    runs: InlineRun[],
    base: InlineDocxOpts = {},
  ): any[] => {
    const out: any[] = [];
    for (const run of runs) {
      const tr = new TextRun({
        text: run.text,
        bold: base.bold || run.bold || undefined,
        italics: base.italics || run.italic || undefined,
        strike: run.strike || undefined,
        font: run.code ? "Courier New" : base.font ?? "Roboto",
        size: run.code ? (base.size ?? 22) - 2 : base.size ?? 22,
        color: run.link ? "1A5FB4" : base.color,
        underline: run.link ? { type: "single" } : undefined,
      });
      if (run.link) {
        out.push(new ExternalHyperlink({ children: [tr], link: run.link }));
      } else {
        out.push(tr);
      }
    }
    return out;
  };

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

  const pushMermaidBlock = async (seg: TextSegment) => {
    const result = await renderMermaidToPng(seg.content.trim(), 1800);
    if (!result) {
      pushCodeBlock({ ...seg, type: "code" });
      return;
    }
    try {
      const imgBuffer = await result.blob.arrayBuffer();
      // Mirror the PDF sizing rule: ~60% of the content width by default,
      // hard-cap the height at the page's content area so tall diagrams
      // can't overflow. A4 portrait @ 96 DPI with 1in margins ≈ 602×930 px.
      const docxContentWidthPx = 602;
      const docxContentHeightPx = 930;
      let imgWidth = Math.round(docxContentWidthPx * 0.6);
      let imgHeight = Math.max(Math.round(imgWidth * result.aspectRatio), 40);
      if (imgHeight > docxContentHeightPx) {
        imgHeight = docxContentHeightPx;
        imgWidth = Math.max(
          Math.round(imgHeight / result.aspectRatio),
          40,
        );
      }
      children.push(
        new Paragraph({
          children: [
            new ImageRun({
              data: imgBuffer,
              transformation: { width: imgWidth, height: imgHeight },
              type: "png",
            }),
          ],
          spacing: { before: 120, after: 120 },
          alignment: AlignmentType.CENTER,
        }),
      );
    } catch {
      pushCodeBlock({ ...seg, type: "code" });
    }
  };

  const makeTableCell = (text: string, header: boolean) => {
    const link = extractCellSingleLink(text);
    // Word resolves the hyperlink Target as a raw filesystem path — `%20`,
    // `%D0%9F`… encoding (which we add for markdown/PDF) makes Word search
    // for a literally-named file and fail with "Cannot open the specified
    // file". Decode for the DOCX side.
    const docxLinkTarget = link ? safeDecode(link.url) : "";
    const runs: any[] = link
      ? [
          new ExternalHyperlink({
            children: [
              new TextRun({
                text: link.label || " ",
                size: 20,
                font: "Roboto",
                bold: header,
                color: "1A5FB4",
                underline: { type: "single" },
              }),
            ],
            link: docxLinkTarget,
          }),
        ]
      : [
          new TextRun({
            text: stripMarkdownInline(text) || " ",
            size: 20,
            font: "Roboto",
            bold: header,
          }),
        ];
    return new TableCell({
      children: [
        new Paragraph({
          children: runs,
          spacing: { before: 40, after: 40 },
        }),
      ],
      shading: header
        ? { type: ShadingType.CLEAR, fill: "EBEBF5" }
        : undefined,
    });
  };

  const pushTableBlock = (block: TextBlock) => {
    if (!block.header || !block.rows) return;
    const rows = [
      new TableRow({
        tableHeader: true,
        children: block.header.map((c) => makeTableCell(c, true)),
      }),
      ...block.rows.map(
        (row) =>
          new TableRow({
            children: row.map((c) => makeTableCell(c, false)),
          }),
      ),
    ];
    children.push(
      new Table({
        rows,
        width: { size: 100, type: WidthType.PERCENTAGE },
      }),
    );
    children.push(new Paragraph({ spacing: { after: 120 } }));
  };

  const pushHrBlock = () => {
    children.push(
      new Paragraph({
        border: {
          bottom: { style: BorderStyle.SINGLE, size: 6, color: "CCCCCC" },
        },
        spacing: { before: 120, after: 160 },
      }),
    );
  };

  const DOCX_BULLETS = ["•", "◦", "▪", "▫", "·", "·"];

  const computeBullet = (
    item: NonNullable<TextBlock["items"]>[number],
    counters: number[],
  ): string => {
    if (item.task === "todo") return "☐";
    if (item.task === "done") return "☑";
    if (item.ordered) {
      counters[item.level] = (counters[item.level] ?? 0) + 1;
      return `${counters[item.level]}.`;
    }
    counters[item.level] = 0;
    return DOCX_BULLETS[Math.min(item.level, DOCX_BULLETS.length - 1)];
  };

  const pushListBlock = (
    block: TextBlock,
    opts: { inCard?: boolean } = {},
  ) => {
    if (!block.items?.length) return;
    const counters: number[] = [];
    let prevLevel = -1;
    for (const item of block.items) {
      if (item.level < prevLevel) {
        for (let k = item.level + 1; k < counters.length; k++) counters[k] = 0;
      }
      const bullet = computeBullet(item, counters);
      prevLevel = item.level;

      const baseIndent = opts.inCard ? 200 : 0;
      const stepTwips = 360;
      const prefixRun = new TextRun({
        text: `${bullet}  `,
        size: 22,
        font: "Roboto",
      });
      const inlineChildren = inlineRunsToDocx(parseInlineRuns(item.text), {
        size: 22,
        font: "Roboto",
      });
      children.push(
        new Paragraph({
          children: [prefixRun, ...inlineChildren],
          indent: { left: baseIndent + item.level * stepTwips },
          spacing: { after: 40 },
          ...(opts.inCard
            ? { border: cardBorder, shading: cardShading }
            : {}),
        }),
      );
    }
  };

  const pushQuoteBlock = (
    block: TextBlock,
    opts: { inCard?: boolean } = {},
  ) => {
    const quoteBorder = {
      left: { style: BorderStyle.SINGLE, size: 18, color: "B0B0B0" },
    };
    const quoteShading = {
      type: ShadingType.CLEAR,
      fill: "F4F4F6",
    };
    const inner = parseTextBlocks(block.content ?? "");
    for (const block2 of inner) {
      if (block2.type === "list") {
        const items = block2.items ?? [];
        const counters: number[] = [];
        let prevLevel = -1;
        for (const item of items) {
          if (item.level < prevLevel) {
            for (let k = item.level + 1; k < counters.length; k++)
              counters[k] = 0;
          }
          const bullet = computeBullet(item, counters);
          prevLevel = item.level;
          const prefixRun = new TextRun({
            text: `${bullet}  `,
            size: 22,
            font: "Roboto",
            color: "606060",
          });
          const inlineChildren = inlineRunsToDocx(parseInlineRuns(item.text), {
            size: 22,
            font: "Roboto",
            color: "606060",
          });
          children.push(
            new Paragraph({
              children: [prefixRun, ...inlineChildren],
              indent: { left: (opts.inCard ? 320 : 240) + item.level * 360 },
              spacing: { after: 40 },
              border: opts.inCard
                ? { ...cardBorder, left: quoteBorder.left }
                : quoteBorder,
              shading: opts.inCard ? cardShading : quoteShading,
            }),
          );
        }
        continue;
      }
      const content = block2.content ?? "";
      for (const para of content.split(/\n{2,}/)) {
        if (!para.trim()) continue;
        children.push(
          new Paragraph({
            children: inlineRunsToDocx(parseInlineRuns(para.trim()), {
              size: 22,
              font: "Roboto",
              color: "606060",
              italics: true,
            }),
            indent: { left: opts.inCard ? 320 : 240 },
            spacing: { after: 40 },
            border: opts.inCard
              ? { ...cardBorder, left: quoteBorder.left }
              : quoteBorder,
            shading: opts.inCard ? cardShading : quoteShading,
          }),
        );
      }
    }
  };

  const pushTextBlocks = (text: string, opts: { inCard?: boolean } = {}) => {
    const blocks = parseTextBlocks(text);
    for (const block of blocks) {
      if (block.type === "heading") {
        const lvl = Math.min(block.level ?? 1, 6);
        children.push(
          new Paragraph({
            children: inlineRunsToDocx(parseInlineRuns(block.content ?? ""), {
              bold: true,
              font: "Roboto",
            }),
            heading: DOCX_HEADING_MAP[lvl] ?? HeadingLevel.HEADING_6,
            spacing: { before: 200, after: 120 },
          }),
        );
      } else if (block.type === "table") {
        pushTableBlock(block);
      } else if (block.type === "hr") {
        pushHrBlock();
      } else if (block.type === "list") {
        pushListBlock(block, opts);
      } else if (block.type === "quote") {
        pushQuoteBlock(block, opts);
      } else {
        const content = block.content ?? "";
        const paras = content.split(/\n{2,}/);
        for (const para of paras) {
          if (!para.trim()) continue;
          children.push(
            new Paragraph({
              children: inlineRunsToDocx(parseInlineRuns(para.trim()), {
                size: 24,
                font: "Roboto",
              }),
              spacing: { after: 80 },
            }),
          );
        }
      }
    }
  };

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

  const pushImageParagraph = async (
    img: ExportImage,
    opts: {
      width: number;
      /** If absent, derived from img.aspectRatio (fallback 0.55). */
      height?: number;
      /** Cap on rendered height in pt (default ~720 — fits A4 page). */
      maxHeight?: number;
      spacing: { before: number; after: number };
      inCard?: boolean;
    },
  ) => {
    try {
      const aspect = img.aspectRatio && img.aspectRatio > 0 ? img.aspectRatio : 0.55;
      const maxHeight = opts.maxHeight ?? 720;
      let width = opts.width;
      let height = opts.height ?? Math.round(width * aspect);
      if (height > maxHeight) {
        height = maxHeight;
        width = Math.round(height / aspect);
      }
      const imgBuffer = await blobToArrayBuffer(img.blob);
      children.push(
        new Paragraph({
          children: [
            new ImageRun({
              data: imgBuffer,
              transformation: { width, height },
              type: "png",
            }),
          ],
          spacing: opts.spacing,
          alignment: AlignmentType.CENTER,
          ...(opts.inCard
            ? {
                border: cardBorder,
                shading: cardShading,
                indent: { left: 200 },
              }
            : {}),
        }),
      );
    } catch {
      // skip broken images
    }
  };

  const pushAttachmentsList = (names: string[]) => {
    if (names.length === 0) return;
    children.push(
      new Paragraph({
        children: [
          new TextRun({
            text: `Вложения: ${names.join(", ")}`,
            size: 18,
            font: "Roboto",
            italics: true,
            color: "888888",
          }),
        ],
        spacing: { before: 0, after: 120 },
      }),
    );
  };

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
        if (seg.type === "mermaid") {
          await pushMermaidBlock(seg);
          continue;
        }
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
                children: inlineRunsToDocx(
                  parseInlineRuns(block.content ?? ""),
                  { size: 22, bold: true, font: "Roboto" },
                ),
                heading: DOCX_HEADING_MAP[lvl] ?? HeadingLevel.HEADING_6,
                spacing: { before: 120, after: 60 },
                border: cardBorder,
                shading: cardShading,
                indent: { left: 200 },
              }),
            );
          } else if (block.type === "table") {
            pushTableBlock(block);
          } else if (block.type === "hr") {
            pushHrBlock();
          } else if (block.type === "list") {
            pushListBlock(block, { inCard: true });
          } else if (block.type === "quote") {
            pushQuoteBlock(block, { inCard: true });
          } else {
            const content = block.content ?? "";
            for (const para of content.split(/\n{2,}/)) {
              if (!para.trim()) continue;
              children.push(
                new Paragraph({
                  children: inlineRunsToDocx(parseInlineRuns(para.trim()), {
                    size: 22,
                    font: "Roboto",
                  }),
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
        await pushImageParagraph(img, {
          width: 460,
          spacing: { before: 80, after: 80 },
          inCard: true,
        });
      }
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
        children.push(
          new Paragraph({
            children: inlineRunsToDocx(parseInlineRuns(headingText), {
              font: "Roboto",
              size: 36,
              bold: true,
              color: "000000",
            }),
            heading: HeadingLevel.HEADING_1,
            spacing: { before: 360, after: 200 },
          }),
        );
      }
      for (const chunk of msg.chunks) {
        if (chunk.type === "image") {
          await pushImageParagraph(chunk.image, {
            width: 500,
            spacing: { before: 120, after: 120 },
          });
        } else if (chunk.type === "inlineMd") {
          await pushInlineMdCard(chunk.section);
        } else if (chunk.type === "attachmentsList") {
          pushAttachmentsList(chunk.names);
        }
      }
      continue;
    }

    for (const chunk of msg.chunks) {
      if (chunk.type === "inlineMd") {
        await pushInlineMdCard(chunk.section);
        continue;
      }
      if (chunk.type === "image") {
        await pushImageParagraph(chunk.image, {
          width: 500,
          spacing: { before: 120, after: 120 },
        });
        continue;
      }
      if (chunk.type === "attachmentsList") {
        pushAttachmentsList(chunk.names);
        continue;
      }
      const segments = parseTextSegments(downshiftHeadings(chunk.content));
      for (const seg of segments) {
        if (seg.type === "mermaid") {
          await pushMermaidBlock(seg);
        } else if (seg.type === "code") {
          pushCodeBlock(seg);
        } else {
          pushTextBlocks(seg.content);
        }
      }
    }

    // Trailing separator after each AI message; suppress the final one when
    // nothing follows so the document doesn't end with a dangling rule.
    const isLastMsg = msgIdx === exportable.length - 1;
    if (!(isLastMsg && bundle.length === 0)) {
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
  }

  if (bundle.length > 0) {
    children.push(
      new Paragraph({
        children: [
          new TextRun({
            text: "Артефакты",
            size: 24,
            font: "Roboto",
            bold: true,
          }),
        ],
        spacing: { before: 240, after: 40 },
      }),
    );
    children.push(
      new Paragraph({
        children: [
          new TextRun({
            text: "В архиве, папка attachments/",
            size: 16,
            font: "Roboto",
            color: "8A8A8A",
          }),
        ],
        spacing: { after: 120 },
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
    background: { color: "FFFFFF" },
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
