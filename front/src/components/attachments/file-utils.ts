import { API_AGENT_PREFIX } from "@/config.ts";

export type AttachmentFileType =
  | "plotly_graph"
  | "image"
  | "audio"
  | "video"
  | "html"
  | "text"
  | "other";

type PathLike =
  | string
  | {
      path?: string;
      sandbox_path?: string;
    }
  | null
  | undefined;

export const resolveAttachmentPath = (value: PathLike): string => {
  if (!value) return "";
  if (typeof value === "string") return value;
  return value.path ?? value.sandbox_path ?? "";
};

export const buildContentByPathUrl = (path: string): string =>
  `${API_AGENT_PREFIX}/files/content/by-path?path=${encodeURIComponent(path)}`;

export const buildContentByPathPreviewUrl = (path: string): string =>
  `${API_AGENT_PREFIX}/files/content/by-path?path=${encodeURIComponent(path)}&redirect_result=json`;

export const inferAttachmentTypeFromPath = (
  path: string,
): AttachmentFileType => {
  const lower = path.toLowerCase();

  if (lower.endsWith(".plotly.json")) return "plotly_graph";

  const dotIdx = lower.lastIndexOf(".");
  const ext = dotIdx >= 0 ? lower.slice(dotIdx + 1) : "";

  const imageExt = ["png", "jpg", "jpeg", "gif", "webp", "bmp", "svg"];
  const audioExt = ["mp3", "wav", "ogg", "m4a", "aac", "flac"];
  const videoExt = ["mp4", "webm", "mov", "m4v"];
  const htmlExt = ["html", "htm"];
  const textExt = [
    "txt",
    "md",
    "csv",
    "json",
    "xml",
    "yaml",
    "yml",
    "toml",
    "ini",
    "cfg",
    "conf",
  ];

  if (imageExt.includes(ext)) return "image";
  if (audioExt.includes(ext)) return "audio";
  if (videoExt.includes(ext)) return "video";
  if (htmlExt.includes(ext)) return "html";
  if (textExt.includes(ext)) return "text";
  return "other";
};

const INLINE_MD_EXT = [".md", ".mmd"] as const;

export function isInlineMarkdownAttachmentPath(path: string): boolean {
  const lower = path.toLowerCase();
  return INLINE_MD_EXT.some((ext) => lower.endsWith(ext));
}

/** Image, plotly, or .md / .mermaid-style .mmd file — shown in chat, embedded in export text. */
export function isRenderableAsChatAttachment(
  fileType: AttachmentFileType,
  path: string,
): boolean {
  if (fileType === "image" || fileType === "plotly_graph") return true;
  if (fileType === "text" && isInlineMarkdownAttachmentPath(path)) return true;
  return false;
}

/** True if this file should be placed in `attachments/` inside the export zip. */
export function shouldBundleInExport(
  fileType: AttachmentFileType,
  path: string,
): boolean {
  if (isRenderableAsChatAttachment(fileType, path)) return false;
  if (fileType === "plotly_graph" || fileType === "image") return false;
  return true;
}
