import React, { useMemo, useState } from "react";
import {
  Folder,
  File as FileIcon,
  FileText,
  Image as ImageIcon,
  Loader,
  Link as LinkIcon,
  Share2,
  ChevronRight,
} from "lucide-react";
import type { Message } from "@langchain/langgraph-sdk";
import type { ToolCall } from "@langchain/core/messages/tool";
import { toast } from "sonner";

import { API_AGENT_PREFIX } from "../../config";
import { apiClient } from "../../lib/api-client";
import { WidgetShell, EmptyState } from "./kit";
import type { FileEntry, FileBrowserPayload } from "./kit";

/**
 * GenUI-виджет файлового браузера, маршрутизируемый по маркеру
 * `widget:"file_browser"` (provider-agnostic, как трекерный Board). Навигация по
 * папкам и публикация идут через REST провайдера (`/{provider}/list|publish`) —
 * без round-trip через модель. Удаления нет: деструктив остаётся за агентом.
 */

function fmtSize(bytes?: number): string {
  if (bytes == null) return "";
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} КБ`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} МБ`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} ГБ`;
}

function fileIcon(entry: FileEntry) {
  if (entry.type === "dir") return Folder;
  const m = entry.mime_type || "";
  if (m.startsWith("image/")) return ImageIcon;
  if (m.startsWith("text/") || /json|xml|csv/.test(m)) return FileText;
  return FileIcon;
}

// Хлебные крошки из пути ("disk:/a/b" → [/, /a, /a/b]). Yandex API принимает
// и "disk:/..", и "/..", поэтому навигируем по очищенному виду.
function crumbs(path: string): { label: string; path: string }[] {
  const clean = path.replace(/^disk:/, "").replace(/^\/+/, "");
  const out = [{ label: "Диск", path: "/" }];
  if (!clean) return out;
  const parts = clean.split("/");
  let acc = "";
  for (const p of parts) {
    acc += `/${p}`;
    out.push({ label: p, path: acc });
  }
  return out;
}

const FileBrowser: React.FC<{
  toolCall: ToolCall;
  resultMessage?: Message;
  isStreaming: boolean;
}> = ({ resultMessage, isStreaming }) => {
  const initial = useMemo<FileBrowserPayload | null>(() => {
    if (!resultMessage) return null;
    try {
      const raw =
        typeof resultMessage.content === "string"
          ? JSON.parse(resultMessage.content)
          : resultMessage.content;
      const inner = (raw as any)?.data ?? raw;
      return inner?.widget === "file_browser" ? inner : null;
    } catch {
      return null;
    }
  }, [resultMessage]);

  const [path, setPath] = useState<string | null>(null);
  const [entries, setEntries] = useState<FileEntry[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [busyPath, setBusyPath] = useState<string | null>(null);

  const provider = initial?.provider ?? "yandex_disk";
  const base = `${API_AGENT_PREFIX}/${provider}`;
  const curPath = path ?? initial?.path ?? "/";
  const curEntries = entries ?? initial?.entries ?? [];

  async function navigate(to: string) {
    setLoading(true);
    try {
      const data = await apiClient.get<FileBrowserPayload>(
        `${base}/list?path=${encodeURIComponent(to)}`,
        { showError: false },
      );
      setPath(data?.path ?? to);
      setEntries(data?.entries ?? []);
    } catch {
      toast.error("Не удалось открыть папку");
    } finally {
      setLoading(false);
    }
  }

  async function publish(entry: FileEntry) {
    setBusyPath(entry.path);
    try {
      const data = await apiClient.post<{ public_url?: string }>(
        `${base}/publish`,
        { path: entry.path },
        { showError: false },
      );
      const url = data?.public_url;
      if (url) {
        setEntries((prev) =>
          (prev ?? curEntries).map((e) =>
            e.path === entry.path ? { ...e, public_url: url } : e,
          ),
        );
        toast.success(`${entry.name}: опубликовано`);
      }
    } catch {
      toast.error(`Не удалось опубликовать ${entry.name}`);
    } finally {
      setBusyPath(null);
    }
  }

  if (!resultMessage) {
    return (
      <WidgetShell>
        <EmptyState loading={isStreaming}>Открываю Диск…</EmptyState>
      </WidgetShell>
    );
  }
  if (!initial) {
    return (
      <WidgetShell>
        <EmptyState tone="error">Некорректный ответ Диска</EmptyState>
      </WidgetShell>
    );
  }

  const bc = crumbs(curPath);

  return (
    <WidgetShell>
      {/* Хлебные крошки */}
      <div className="mb-1.5 flex flex-wrap items-center gap-0.5 px-1 text-[11px] text-muted-foreground">
        {bc.map((c, i) => (
          <span key={c.path} className="inline-flex items-center gap-0.5">
            {i > 0 && <ChevronRight size={11} className="opacity-50" />}
            <button
              type="button"
              disabled={loading || i === bc.length - 1}
              onClick={() => navigate(c.path)}
              className="rounded px-1 hover:text-foreground disabled:hover:text-muted-foreground disabled:font-medium"
            >
              {c.label}
            </button>
          </span>
        ))}
        {loading && <Loader size={11} className="ml-1 animate-spin" />}
      </div>

      {curEntries.length === 0 ? (
        <EmptyState>Папка пуста</EmptyState>
      ) : (
        <div className="flex flex-col">
          {curEntries.map((entry) => {
            const Icon = fileIcon(entry);
            const isDir = entry.type === "dir";
            const busy = busyPath === entry.path;
            return (
              <div
                key={entry.path}
                className="flex items-center gap-2 rounded-md px-1.5 py-1 text-sm hover:bg-muted/50"
              >
                <Icon
                  size={15}
                  className={
                    isDir ? "shrink-0 text-blue-500" : "shrink-0 text-muted-foreground"
                  }
                />
                {isDir ? (
                  <button
                    type="button"
                    disabled={loading}
                    onClick={() => navigate(entry.path)}
                    className="min-w-0 flex-1 truncate text-left font-medium hover:underline"
                  >
                    {entry.name}
                  </button>
                ) : (
                  <span className="min-w-0 flex-1 truncate">{entry.name}</span>
                )}
                {!isDir && (
                  <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">
                    {fmtSize(entry.size)}
                  </span>
                )}
                {!isDir &&
                  (entry.public_url ? (
                    <a
                      href={entry.public_url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex shrink-0 items-center gap-1 text-[11px] text-primary/80 hover:text-primary"
                    >
                      <LinkIcon size={12} /> ссылка
                    </a>
                  ) : (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => publish(entry)}
                      className="inline-flex shrink-0 items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground disabled:opacity-50"
                    >
                      {busy ? (
                        <Loader size={12} className="animate-spin" />
                      ) : (
                        <Share2 size={12} />
                      )}
                      опубликовать
                    </button>
                  ))}
              </div>
            );
          })}
        </div>
      )}
    </WidgetShell>
  );
};

export default FileBrowser;
