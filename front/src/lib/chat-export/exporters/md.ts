import { buildContentByPathUrl } from "@/components/attachments/file-utils";
import { downshiftHeadings } from "../markdown-parse";
import { fetchImageAsBlob } from "../utils";
import type {
  ExportableMessage,
  ExportBundleFile,
  ExportImage,
  InlineMdSection,
} from "../types";

function renderInlineMdAsBlockquote(
  section: InlineMdSection,
  embedImages: boolean,
  imageRefs: ExportImage[],
): string {
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

  const all: string[] = section.filename
    ? [`📄 **${section.filename}**`, "", ...bodyLines]
    : [...bodyLines];
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

  const pushImageLine = (img: ExportImage) => {
    if (embedImages) {
      lines.push(`![${img.name}](${img.name})`);
    } else {
      lines.push(`![${img.name}](${img.dataUrl})`);
    }
    lines.push("");
    imageRefs.push(img);
  };

  for (const msg of exportable) {
    if (msg.role === "user") {
      const headingText = msg.chunks
        .filter((c) => c.type === "text")
        .map((c) => c.content)
        .join(" ")
        .trim();
      if (headingText) {
        lines.push(`# ${headingText}`);
        lines.push("");
      }
      for (const chunk of msg.chunks) {
        if (chunk.type === "image") {
          pushImageLine(chunk.image);
        } else if (chunk.type === "inlineMd") {
          lines.push(
            renderInlineMdAsBlockquote(chunk.section, embedImages, imageRefs),
          );
          lines.push("");
        } else if (chunk.type === "attachmentsList") {
          lines.push(`_Вложения: ${chunk.names.join(", ")}_`);
          lines.push("");
        }
      }
      continue;
    }

    for (const chunk of msg.chunks) {
      if (chunk.type === "text") {
        lines.push(downshiftHeadings(chunk.content));
        lines.push("");
      } else if (chunk.type === "inlineMd") {
        lines.push(
          renderInlineMdAsBlockquote(chunk.section, embedImages, imageRefs),
        );
        lines.push("");
      } else if (chunk.type === "image") {
        pushImageLine(chunk.image);
      } else if (chunk.type === "attachmentsList") {
        lines.push(`_📎 ${chunk.names.join(", ")}_`);
        lines.push("");
      }
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
  return (
    body.trimEnd() +
    "\n\n## Артефакты\n\n_В архиве, папка attachments/_\n\n" +
    list +
    "\n"
  );
}

export async function exportAsMarkdown(
  exportable: ExportableMessage[],
  title: string,
  bundle: ExportBundleFile[],
): Promise<Blob> {
  const hasExportImages = exportable.some((m) =>
    m.chunks.some(
      (c) =>
        c.type === "image" ||
        (c.type === "inlineMd" && c.section.images.length > 0),
    ),
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
  const bundleBlobs = await Promise.all(
    bundle.map((f) =>
      f.blob
        ? Promise.resolve(f.blob)
        : fetchImageAsBlob(buildContentByPathUrl(f.path)),
    ),
  );
  for (let i = 0; i < bundle.length; i++) {
    zip.file(`attachments/${bundle[i].nameInZip}`, bundleBlobs[i]);
  }
  return zip.generateAsync({ type: "blob" });
}
