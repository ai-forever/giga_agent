export interface ExportImage {
  name: string;
  dataUrl: string;
  blob: Blob;
  /** height / width — used by exporters to preserve aspect ratio. */
  aspectRatio?: number;
}

export interface InlineMdSection {
  filename: string;
  body: string;
  images: ExportImage[];
}

export type Chunk =
  | { type: "text"; content: string }
  | { type: "image"; image: ExportImage }
  | { type: "inlineMd"; section: InlineMdSection }
  | { type: "attachmentsList"; names: string[] };

export interface ExportableMessage {
  role: "user" | "assistant";
  chunks: Chunk[];
}

export interface RawAttachment {
  path?: string;
  sandbox_path?: string;
  original_name?: string;
  file_type?: string;
}

export interface ExportBundleFile {
  path: string;
  nameInZip: string;
  /**
   * Pre-computed blob for files that need transformation before bundling
   * (e.g., `plotly.json` rendered to PNG). When present, exporters use this
   * directly instead of fetching the original `path` from the server.
   */
  blob?: Blob;
}

export interface PreparedExport {
  exportable: ExportableMessage[];
  bundle: ExportBundleFile[];
}

export type ExportFormat = "pdf" | "docx" | "md";
