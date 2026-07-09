import type { Message } from "@langchain/langgraph-sdk";
import { buildContentByPathUrl } from "@/components/attachments/file-utils";
import { fetchImageAsBlob } from "./utils";
import { prepareMessagesForExport } from "./prepare";
import { exportAsMarkdown } from "./exporters/md";
import { exportAsPdf } from "./exporters/pdf";
import { exportAsDocx } from "./exporters/docx";
import type { ExportBundleFile, ExportFormat } from "./types";

export type { ExportFormat, ExportBundleFile, PreparedExport } from "./types";
export {
  prepareMessagesForExport,
  extractMessagePair,
  stripAssistantReasoningTags,
} from "./prepare";

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

async function downloadZippedFileWithAttachments(
  mainFileName: string,
  mainBlob: Blob,
  bundle: ExportBundleFile[],
): Promise<void> {
  const JSZip = (await import("jszip")).default;
  const zip = new JSZip();
  zip.file(mainFileName, mainBlob);
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

  if (format === "json") {
    // Raw dump of the full dialogue exactly as stored (all messages,
    // including thinking, tool calls and tool results). No transformation.
    const blob = new Blob([JSON.stringify(messages, null, 2)], {
      type: "application/json",
    });
    downloadBlob(blob, `${safeTitle}.json`);
    return;
  }

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
