import { useMemo, useState } from "react";
import { FileData } from "../interfaces.ts";
import { apiClient } from "../lib/api-client.ts";
import { buildContentByPathUrl } from "../components/attachments/file-utils.ts";

export interface UploadedFile {
  file: File;
  progress: number;
  previewUrl?: string;
  data?: FileData;
  error?: string;
}

export interface AttachmentItem {
  kind: "existing" | "upload";
  file?: File;
  data?: FileData;
  progress: number;
  previewUrl?: string;
  name?: string;
  error?: string;
}

type UploadOptions = {
  threadId?: string;
};

type BackendFilePayload = {
  path?: string;
  sandbox_path?: string;
  original_name?: string;
  file_type?: string;
  size?: number;
  image_id?: string;
  image_path?: string;
};

const detectFileType = (file: File): string => {
  const mime = (file.type || "").toLowerCase();
  if (mime.startsWith("image/")) return "image";
  if (mime.startsWith("audio/")) return "audio";
  if (mime.startsWith("video/")) return "video";
  if (mime === "text/html") return "html";
  if (mime.startsWith("text/")) return "text";

  const name = file.name.toLowerCase();
  if (name.endsWith(".plotly.json")) return "plotly_graph";
  if (name.endsWith(".html") || name.endsWith(".htm")) return "html";
  if (name.endsWith(".txt") || name.endsWith(".md") || name.endsWith(".csv"))
    return "text";
  return "other";
};

const normalizeFileData = (payload: BackendFilePayload): FileData => {
  const path = payload.path ?? payload.sandbox_path ?? "";
  return {
    path,
    original_name: payload.original_name,
    file_type: payload.file_type,
    size: Number(payload.size ?? 0),
    image_id: payload.image_id,
    image_path: payload.image_path,
  };
};

export function useFileUpload() {
  const [uploads, setUploads] = useState<UploadedFile[]>([]);
  const [existingFiles, setExistingFiles] = useState<FileData[]>([]);

  const uploadFiles = (files: File[], options?: UploadOptions) => {
    const oldIndex = uploads.length;
    files.forEach((file, index) => {
      const uploadItem: UploadedFile = { file, progress: 0 };
      const addUpload = (item: UploadedFile) =>
        setUploads((prev) => [...prev, item]);

      if (file.type.startsWith("image/")) {
        const reader = new FileReader();
        reader.onload = () => {
          addUpload({ ...uploadItem, previewUrl: reader.result as string });
        };
        reader.readAsDataURL(file);
      } else {
        addUpload(uploadItem);
      }

      // Определяем индекс нового элемента (последний)
      const idx = oldIndex + index;
      const formData = new FormData();
      formData.append("file", file);
      formData.append("file_type", detectFileType(file));
      if (options?.threadId) {
        formData.append("thread_id", options.threadId);
      }

      setUploads((prev) => {
        const next = [...prev];
        if (next[idx]) next[idx] = { ...next[idx], progress: 10 };
        return next;
      });

      apiClient
        .post<BackendFilePayload>("/api/files/upload", formData, {
          attachAuth: true,
        })
        .then((res) => {
          const normalized = normalizeFileData(res);
          setUploads((prev) => {
            const next = [...prev];
            if (next[idx])
              next[idx] = { ...next[idx], progress: 100, data: normalized };
            return next;
          });
        })
        .catch(() => {
          // При ошибке удаляем соответствующее вложение
          // TODO: показывать ошибку (возможно с возможностью прикрепить повторно)
          setUploads((prev) => prev.filter((u) => u.file !== file));
        });
    });
  };

  const removeUpload = (index: number) => {
    setUploads((prev) => prev.filter((_, i) => i !== index));
  };

  const resetUploads = () => setUploads([]);

  const removeExisting = (index: number) => {
    setExistingFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const items: AttachmentItem[] = useMemo(() => {
    const mappedExisting: AttachmentItem[] = existingFiles.map((raw) => {
      const f = normalizeFileData(raw as BackendFilePayload);
      const isImage = f.file_type === "image";
      const fileName = f.original_name ?? (f.path.split("/").pop() || f.path);
      return {
        kind: "existing",
        data: f,
        progress: 100,
        previewUrl: isImage ? buildContentByPathUrl(f.path) : undefined,
        name: !isImage ? fileName : undefined,
      };
    });
    const mappedUploads: AttachmentItem[] = uploads.map((u) => ({
      kind: "upload",
      file: u.file,
      data: u.data,
      progress: u.progress,
      previewUrl: u.previewUrl,
      name: u.file?.name,
      error: u.error,
    }));
    return [...mappedExisting, ...mappedUploads];
  }, [existingFiles, uploads]);

  const removeItem = (index: number) => {
    if (index < existingFiles.length) {
      removeExisting(index);
    } else {
      removeUpload(index - existingFiles.length);
    }
  };

  const getAllFileData = (): FileData[] => {
    const fromUploads = uploads
      .map((u) => u.data)
      .filter((x): x is FileData => Boolean(x));
    return [...existingFiles, ...fromUploads];
  };

  return {
    uploads,
    uploadFiles,
    removeUpload,
    resetUploads,
    setUploads,
    existingFiles,
    setExistingFiles,
    removeExisting,
    items,
    removeItem,
    getAllFileData,
  };
}
