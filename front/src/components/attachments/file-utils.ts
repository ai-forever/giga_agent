import { resolveApiUrl } from "@/lib/api-client";

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
  resolveApiUrl(`/api/files/content/by-path?path=${encodeURIComponent(path)}`);

export const buildContentByPathPreviewUrl = (path: string): string =>
  resolveApiUrl(
    `/api/files/content/by-path?path=${encodeURIComponent(path)}&redirect_result=json`,
  );

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
