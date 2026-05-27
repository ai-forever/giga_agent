import React, { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { FileUp, Trash2 } from "lucide-react";

import { API_AGENT_PREFIX } from "@/config.ts";
import { apiClient, ApiError } from "@/lib/api-client";
import { Button } from "@/components/ui/button";

const ACCEPTED_FILE_EXTENSIONS = [
  ".pdf",
  ".txt",
  ".md",
  ".markdown",
  ".html",
  ".doc",
  ".docx",
];

type DocumentItem = {
  id: string;
  metadata?: {
    name?: string;
    created_at?: string | null;
  } | null;
};

const errorDetail = (e: unknown, fallback: string): string => {
  if (e instanceof ApiError) return e.message || fallback;
  if (e instanceof Error) return e.message || fallback;
  return fallback;
};

interface Props {
  collectionId: string | null;
}

const KnowledgeSection: React.FC<Props> = ({ collectionId }) => {
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const baseUrl = collectionId
    ? `${API_AGENT_PREFIX}/rag/collections/${encodeURIComponent(collectionId)}/documents`
    : null;

  const reload = useCallback(
    async (signal?: AbortSignal) => {
      if (!baseUrl) return;
      setLoading(true);
      try {
        const docs = await apiClient.get<DocumentItem[]>(
          `${baseUrl}?limit=100`,
          { signal, showError: false },
        );
        setDocuments(docs);
      } catch (e) {
        if (signal?.aborted) return;
        console.error("Failed to load knowledge documents", e);
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    },
    [baseUrl],
  );

  useEffect(() => {
    if (!baseUrl) return;
    const ctrl = new AbortController();
    void reload(ctrl.signal);
    return () => ctrl.abort();
  }, [baseUrl, reload]);

  if (!collectionId) {
    return (
      <div className="flex flex-col gap-2">
        <div className="text-sm font-medium">Знания проекта</div>
        <div className="text-sm text-muted-foreground">
          Чтобы загружать файлы, сконфигурируйте embedding-модель в настройках —
          тогда у проекта появится своя коллекция.
        </div>
      </div>
    );
  }

  const handleFiles = async (fileList: FileList | null) => {
    if (!fileList || fileList.length === 0 || !baseUrl) return;
    const files = Array.from(fileList);
    const metadatas = files.map((file) => ({
      name: file.name,
      size: file.size,
      created_at: new Date().toISOString(),
    }));
    const formData = new FormData();
    files.forEach((file) => formData.append("files", file, file.name));
    formData.append("metadatas_json", JSON.stringify(metadatas));

    setUploading(true);
    try {
      await apiClient.post(baseUrl, formData, { showError: false });
      toast.success(
        files.length === 1
          ? `Загружено: ${files[0].name}`
          : `Загружено файлов: ${files.length}`,
      );
      await reload();
    } catch (e) {
      toast.error("Не удалось загрузить", {
        description: errorDetail(e, "Попробуйте ещё раз."),
      });
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleDelete = async (docId: string) => {
    if (!baseUrl) return;
    try {
      await apiClient.delete(`${baseUrl}/${encodeURIComponent(docId)}`, {
        showError: false,
      });
      setDocuments((prev) => prev.filter((d) => d.id !== docId));
    } catch (e) {
      toast.error("Не удалось удалить", {
        description: errorDetail(e, "Попробуйте ещё раз."),
      });
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <div className="text-sm font-medium">
          Знания проекта {documents.length > 0 && `(${documents.length})`}
        </div>
        <div>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept={ACCEPTED_FILE_EXTENSIONS.join(",")}
            className="hidden"
            onChange={(e) => void handleFiles(e.target.files)}
          />
          <Button
            size="sm"
            variant="outline"
            disabled={uploading}
            onClick={() => fileInputRef.current?.click()}
          >
            <FileUp className="w-4 h-4 mr-1" />
            {uploading ? "Загрузка…" : "Загрузить"}
          </Button>
        </div>
      </div>

      {loading && documents.length === 0 ? (
        <div className="text-sm text-muted-foreground">Загрузка…</div>
      ) : documents.length === 0 ? (
        <div className="text-sm text-muted-foreground">
          Файлов пока нет. PDF, DOCX, TXT, MD, HTML.
        </div>
      ) : (
        <div className="flex flex-col gap-1">
          {documents.map((d) => (
            <div
              key={d.id}
              className="flex items-center justify-between gap-2 px-3 py-2 rounded-lg hover:bg-muted text-sm"
            >
              <span className="truncate flex-1 min-w-0">
                {d.metadata?.name ?? "document"}
              </span>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 text-muted-foreground hover:text-destructive"
                onClick={() => void handleDelete(d.id)}
                aria-label="Удалить"
              >
                <Trash2 className="w-4 h-4" />
              </Button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default KnowledgeSection;
