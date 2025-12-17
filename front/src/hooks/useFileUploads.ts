import { useMemo, useState } from "react";
import axios from "axios";
import { FileData } from "../interfaces.ts";

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

export function useFileUpload() {
  const [uploads, setUploads] = useState<UploadedFile[]>([]);
  const [existingFiles, setExistingFiles] = useState<FileData[]>([]);

  const uploadFiles = (files: File[]) => {
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

      axios
        .post("/files/upload/", formData, {
          onUploadProgress: (event) => {
            const pct = event.progress || 0;
            setUploads((prev) => {
              const next = [...prev];
              if (next[idx])
                next[idx] = {
                  ...next[idx],
                  progress: Math.min(Math.round(pct * 100), 95),
                };
              return next;
            });
          },
        })
        .then((res) => {
          setUploads((prev) => {
            const next = [...prev];
            if (next[idx])
              next[idx] = { ...next[idx], progress: 100, data: res.data };
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
    const mappedExisting: AttachmentItem[] = existingFiles.map((f) => {
      const isImage = Boolean(f.file_type === "image");
      return {
        kind: "existing",
        data: f,
        progress: 100,
        previewUrl: isImage ? `/files/${f.path}` : undefined,
        name: !isImage ? f.path.replace(/^files\//, "") : undefined,
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
