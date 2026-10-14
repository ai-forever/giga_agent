import React, { useState, useEffect, useCallback, useRef } from "react";
import {
  Github,
  Trash2,
  Upload,
  Download,
  ChevronDown,
  ChevronUp,
  Zap,
  FileText,
  FolderSync,
  Files,
  Search,
  ExternalLink,
  RefreshCw,
  CheckIcon,
  CheckCircle2,
  AlertCircle,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { API_AGENT_PREFIX } from "@/config";
import { apiClient } from "@/lib/api-client";
import { useConfirm } from "@/components/providers/confirm";

interface SkillSummary {
  id: string;
  name: string;
  description: string;
  is_enabled: boolean;
  source_type: string;
  source_url?: string | null;
  created_at: string;
  is_readonly?: boolean;
  can_toggle?: boolean;
}

interface BuiltinSkillInfo {
  name: string;
  description: string;
  is_installed: boolean;
}

interface GithubPreviewSkill {
  name: string;
  description: string;
  path: string;
  manifest_url: string;
  already_installed: boolean;
  installed_commit: string | null;
}

interface GithubPreviewResponse {
  source: string;
  ref: string;
  commit: string;
  skills: GithubPreviewSkill[];
  warnings: string[];
  cache_state: "fresh" | "miss";
  cached_at: number | null;
}

interface GithubInstallResult {
  name: string;
  path: string;
  status: "installed" | "already-installed" | "error";
  error?: string | null;
  skill_id?: string | null;
  source_url?: string | null;
  commit?: string | null;
}

interface GithubInstallResponse {
  source: string;
  ref: string;
  commit: string;
  results: GithubInstallResult[];
  warnings: string[];
  cache_state: "fresh" | "miss";
  cached_at: number | null;
}

interface GithubUpdateCheckItem {
  skill_id: string;
  name: string;
  source: string | null;
  ref: string | null;
  path: string | null;
  status:
    | "up_to_date"
    | "update_available"
    | "removed_from_source"
    | "uncheckable"
    | "error";
  available_commit: string | null;
  error: string | null;
}

interface GithubUpdateCheckResponse {
  items: GithubUpdateCheckItem[];
}

interface SkillDetail {
  skill: {
    id: string;
    owner_id: string;
    name: string;
    description: string;
    source_type: string;
    storage_path: string;
    is_enabled: boolean;
    created_at: string;
    updated_at: string;
  };
  body: string;
}

const SOURCE_LABELS: Record<string, string> = {
  builtin: "Встроенный",
  upload: "Загружен",
  local_dir: "Локальный",
  github: "GitHub",
};

const SkillItem: React.FC<{
  skill: SkillSummary;
  onToggle: (id: string, enabled: boolean) => void;
  onDelete: (id: string) => void;
  onView: (id: string) => void;
  githubUpdate?: GithubUpdateCheckItem;
  onUpdateGithub?: (update: GithubUpdateCheckItem) => void;
  disabled?: boolean;
}> = ({
  skill,
  onToggle,
  onDelete,
  onView,
  githubUpdate,
  onUpdateGithub,
  disabled,
}) => {
  const canToggle = skill.can_toggle !== false && !skill.is_readonly;

  return (
    <div className="flex items-center justify-between p-4 border border-border rounded-lg bg-card hover:bg-accent/50 transition-colors">
      <div className="flex flex-col gap-1 flex-1 min-w-0 mr-4">
        <div className="flex items-center gap-2">
          <span className="font-medium truncate">{skill.name}</span>
          <Badge variant="outline" className="text-xs shrink-0">
            {SOURCE_LABELS[skill.source_type] || skill.source_type}
          </Badge>
          {skill.is_readonly && (
            <Badge variant="secondary" className="text-xs shrink-0">
              read-only
            </Badge>
          )}
          {githubUpdate?.status === "update_available" && (
            <Badge variant="outline" className="text-xs shrink-0">
              Доступно обновление
            </Badge>
          )}
          {githubUpdate?.status === "removed_from_source" && (
            <Badge variant="destructive" className="text-xs shrink-0">
              Удалён из источника
            </Badge>
          )}
          {githubUpdate?.status === "uncheckable" && (
            <Badge variant="secondary" className="text-xs shrink-0">
              Переустановите для проверки
            </Badge>
          )}
          {skill.source_url && skill.source_type === "github" && (
            <a
              href={skill.source_url}
              target="_blank"
              rel="noreferrer"
              className="text-muted-foreground hover:text-foreground shrink-0"
              title="Открыть источник на GitHub"
              onClick={(event) => event.stopPropagation()}
            >
              <ExternalLink className="size-3.5" />
            </a>
          )}
        </div>
        {skill.description && (
          <span className="text-sm text-muted-foreground line-clamp-2">
            {skill.description}
          </span>
        )}
      </div>
      <div className="flex items-center gap-1 shrink-0">
        {githubUpdate?.status === "update_available" && onUpdateGithub && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => onUpdateGithub(githubUpdate)}
            disabled={disabled}
          >
            <RefreshCw className="size-3.5 mr-1" />
            Обновить
          </Button>
        )}
        <Button
          variant="ghost"
          size="icon"
          onClick={() => onView(skill.id)}
          title="Просмотр"
          disabled={disabled}
        >
          <FileText className="size-4" />
        </Button>
        {canToggle && (
          <Switch
            checked={skill.is_enabled}
            onCheckedChange={(checked) => onToggle(skill.id, checked)}
            aria-label={skill.is_enabled ? "Отключить" : "Включить"}
            disabled={disabled}
          />
        )}
        <Button
          variant="ghost"
          size="icon"
          onClick={() => onDelete(skill.id)}
          title={skill.is_readonly ? "Read-only" : "Удалить"}
          disabled={disabled || skill.is_readonly}
        >
          <Trash2 className="size-4 text-destructive" />
        </Button>
      </div>
    </div>
  );
};

export const SkillsSettings: React.FC = () => {
  const confirm = useConfirm();
  const [skills, setSkills] = useState<SkillSummary[]>([]);
  const [builtins, setBuiltins] = useState<BuiltinSkillInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [githubDialogOpen, setGithubDialogOpen] = useState(false);
  const [githubSource, setGithubSource] = useState("");
  const [githubPreview, setGithubPreview] =
    useState<GithubPreviewResponse | null>(null);
  const [githubSelected, setGithubSelected] = useState<Record<string, boolean>>(
    {},
  );
  const [githubReplace, setGithubReplace] = useState<Record<string, boolean>>(
    {},
  );
  const [githubResults, setGithubResults] = useState<GithubInstallResult[]>([]);
  const [githubPreviewLoading, setGithubPreviewLoading] = useState(false);
  const [githubInstalling, setGithubInstalling] = useState(false);
  const [githubUpdates, setGithubUpdates] = useState<
    Record<string, GithubUpdateCheckItem>
  >({});
  const [githubUpdatesLoading, setGithubUpdatesLoading] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [showBuiltinCatalog, setShowBuiltinCatalog] = useState(false);
  const [viewDetail, setViewDetail] = useState<SkillDetail | null>(null);
  const [viewDialogOpen, setViewDialogOpen] = useState(false);
  const dragCounterRef = useRef(0);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const loadSkills = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiClient.get<SkillSummary[]>(
        `${API_AGENT_PREFIX}/skills/`,
      );
      setSkills(data);
    } catch {
      toast.error("Не удалось загрузить список скиллов");
    } finally {
      setLoading(false);
    }
  }, []);

  const loadBuiltins = useCallback(async () => {
    try {
      const data = await apiClient.get<BuiltinSkillInfo[]>(
        `${API_AGENT_PREFIX}/skills/builtin/list`,
      );
      setBuiltins(data);
    } catch {
      // non-critical
    }
  }, []);

  useEffect(() => {
    loadSkills();
    loadBuiltins();
  }, [loadSkills, loadBuiltins]);

  const handleToggle = async (id: string, enabled: boolean) => {
    try {
      await apiClient.patch(`${API_AGENT_PREFIX}/skills/${id}`, {
        is_enabled: enabled,
      });
      setSkills((prev) =>
        prev.map((s) => (s.id === id ? { ...s, is_enabled: enabled } : s)),
      );
      toast.success(enabled ? "Скилл включён" : "Скилл отключён");
    } catch {
      toast.error("Не удалось обновить скилл");
    }
  };

  const handleDelete = async (id: string) => {
    const skill = skills.find((s) => s.id === id);
    const ok = await confirm({
      title: "Удалить скилл?",
      description: `Скилл "${skill?.name}" будет удалён вместе с файлами.`,
      confirmText: "Удалить",
      cancelText: "Отмена",
    });
    if (!ok) return;

    try {
      await apiClient.delete(`${API_AGENT_PREFIX}/skills/${id}`);
      setSkills((prev) => prev.filter((s) => s.id !== id));
      loadBuiltins();
      toast.success("Скилл удалён");
    } catch {
      toast.error("Не удалось удалить скилл");
    }
  };

  const uploadSkillArchive = useCallback(
    async (file: File) => {
      const maxSize = 10 * 1024 * 1024;
      if (file.size > maxSize) {
        toast.error("Размер архива не может превышать 10 МБ");
        return;
      }

      setUploading(true);
      try {
        const formData = new FormData();
        formData.append("file", file);
        await apiClient.post(`${API_AGENT_PREFIX}/skills/upload`, formData);
        toast.success("Скилл установлен");
        loadSkills();
        loadBuiltins();
      } catch (err: any) {
        const msg = err?.data?.detail || "Не удалось загрузить скилл";
        toast.error(msg);
      } finally {
        setUploading(false);
      }
    },
    [loadBuiltins, loadSkills],
  );

  const handleUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = "";
    void uploadSkillArchive(file);
  };

  const handleInstallBuiltin = async (name: string) => {
    try {
      await apiClient.post(`${API_AGENT_PREFIX}/skills/install-builtin`, {
        skill_name: name,
      });
      toast.success(`Скилл "${name}" установлен`);
      loadSkills();
      loadBuiltins();
    } catch (err: any) {
      const msg = err?.data?.detail || "Не удалось установить скилл";
      toast.error(msg);
    }
  };

  const resetGithubDialog = () => {
    setGithubSource("");
    setGithubPreview(null);
    setGithubSelected({});
    setGithubReplace({});
    setGithubResults([]);
    setGithubPreviewLoading(false);
    setGithubInstalling(false);
  };

  const handleGithubPreview = async () => {
    const source = githubSource.trim();
    if (!source) {
      toast.error("Укажите GitHub-репозиторий или URL скилла");
      return;
    }

    setGithubPreviewLoading(true);
    setGithubPreview(null);
    setGithubResults([]);
    try {
      const data = await apiClient.post<GithubPreviewResponse>(
        `${API_AGENT_PREFIX}/skills/github/preview`,
        { source },
      );
      const visibleSkills = data.skills.filter(
        (skill) => skill.name.toLowerCase() !== "hyperframes",
      );
      const preview = { ...data, skills: visibleSkills };
      const directPath = /github\.com\/[^/]+\/[^/]+\/tree\//i.test(source);
      const selected = Object.fromEntries(
        visibleSkills.map((skill) => [
          skill.path,
          directPath && visibleSkills.length === 1 && !skill.already_installed,
        ]),
      );
      const replace = Object.fromEntries(
        visibleSkills.map((skill) => [
          skill.path,
          skill.already_installed && skill.installed_commit !== data.commit,
        ]),
      );
      setGithubPreview(preview);
      setGithubSelected(selected);
      setGithubReplace(replace);
    } catch (err: any) {
      const msg =
        err?.data?.detail || "Не удалось просмотреть GitHub-репозиторий";
      toast.error(msg);
    } finally {
      setGithubPreviewLoading(false);
    }
  };

  const handleGithubInstall = async () => {
    if (!githubPreview) return;
    const selected = githubPreview.skills.filter(
      (skill) => githubSelected[skill.path],
    );
    if (selected.length === 0) {
      toast.error("Выберите хотя бы один скилл");
      return;
    }

    const replacing = selected.filter((skill) => githubReplace[skill.path]);
    if (replacing.length > 0) {
      const ok = await confirm({
        title: "Обновить или заменить скиллы?",
        description: `Будут заменены файлы: ${replacing.map((skill) => skill.name).join(", ")}. Действие явно подтверждено только для выбранных скиллов.`,
        confirmText: "Обновить",
        cancelText: "Отмена",
      });
      if (!ok) return;
    }

    setGithubInstalling(true);
    try {
      const data = await apiClient.post<GithubInstallResponse>(
        `${API_AGENT_PREFIX}/skills/github/install`,
        {
          source: githubSource.trim(),
          skills: selected.map((skill) => ({
            path: skill.path,
            replace_existing: githubReplace[skill.path] === true,
          })),
        },
      );
      setGithubResults(data.results);
      await loadSkills();
      await loadBuiltins();
      const failed = data.results.filter((result) => result.status === "error");
      if (failed.length > 0) {
        toast.error(`Не удалось установить ${failed.length} скилл(ов)`);
      } else {
        toast.success("GitHub-скиллы установлены");
        setGithubDialogOpen(false);
      }
    } catch (err: any) {
      const msg = err?.data?.detail || "Не удалось установить GitHub-скиллы";
      toast.error(msg);
    } finally {
      setGithubInstalling(false);
    }
  };

  const handleCheckGithubUpdates = async () => {
    setGithubUpdatesLoading(true);
    try {
      const data = await apiClient.post<GithubUpdateCheckResponse>(
        `${API_AGENT_PREFIX}/skills/github/updates/check`,
        {},
      );
      setGithubUpdates(
        Object.fromEntries(data.items.map((item) => [item.skill_id, item])),
      );
      const available = data.items.filter(
        (item) => item.status === "update_available",
      ).length;
      toast.success(
        available > 0
          ? `Доступно обновлений: ${available}`
          : "GitHub-скиллы актуальны",
      );
    } catch (err: any) {
      toast.error(err?.data?.detail || "Не удалось проверить обновления");
    } finally {
      setGithubUpdatesLoading(false);
    }
  };

  const handleGithubUpdate = async (update: GithubUpdateCheckItem) => {
    if (!update.source || !update.ref || update.path == null) {
      toast.error("Для этого скилла недоступно обновление");
      return;
    }
    const ok = await confirm({
      title: "Обновить скилл?",
      description: `Файлы скилла "${update.name}" будут заменены версией из GitHub.`,
      confirmText: "Обновить",
      cancelText: "Отмена",
    });
    if (!ok) return;

    const encodedRef = encodeURIComponent(update.ref);
    const encodedPath = update.path
      ? `/${update.path
          .split("/")
          .map((part) => encodeURIComponent(part))
          .join("/")}`
      : "";
    const source = `https://github.com/${update.source}/tree/${encodedRef}${encodedPath}`;
    try {
      const data = await apiClient.post<GithubInstallResponse>(
        `${API_AGENT_PREFIX}/skills/github/install`,
        {
          source,
          skills: [{ path: update.path, replace_existing: true }],
        },
      );
      const result = data.results[0];
      if (!result || result.status === "error") {
        throw new Error(result?.error || "Не удалось обновить скилл");
      }
      toast.success(`Скилл "${update.name}" обновлён`);
      await loadSkills();
      await handleCheckGithubUpdates();
    } catch (err: any) {
      toast.error(
        err?.data?.detail || err?.message || "Не удалось обновить скилл",
      );
    }
  };

  const handleSyncLocal = async () => {
    try {
      await apiClient.post(`${API_AGENT_PREFIX}/skills/sync-local`, {
        dirs: [],
      });
      toast.success("Синхронизация завершена");
      loadSkills();
    } catch {
      toast.error("Не удалось синхронизировать");
    }
  };

  const handleView = async (id: string) => {
    try {
      const detail = await apiClient.get<SkillDetail>(
        `${API_AGENT_PREFIX}/skills/${id}`,
      );
      setViewDetail(detail);
      setViewDialogOpen(true);
    } catch {
      toast.error("Не удалось загрузить содержимое скилла");
    }
  };

  useEffect(() => {
    const hasFiles = (e: DragEvent) =>
      Array.from(e.dataTransfer?.types ?? []).includes("Files");

    const onDragEnter = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      dragCounterRef.current += 1;
      if (!uploading) setIsDragging(true);
    };
    const onDragOver = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      if (e.dataTransfer) {
        e.dataTransfer.dropEffect = uploading ? "none" : "copy";
      }
    };
    const onDragLeave = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      dragCounterRef.current = Math.max(0, dragCounterRef.current - 1);
      if (dragCounterRef.current === 0) setIsDragging(false);
    };
    const onDrop = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      dragCounterRef.current = 0;
      setIsDragging(false);
      if (uploading) return;

      const file = e.dataTransfer?.files?.[0];
      if (file) void uploadSkillArchive(file);
    };

    window.addEventListener("dragenter", onDragEnter);
    window.addEventListener("dragover", onDragOver);
    window.addEventListener("dragleave", onDragLeave);
    window.addEventListener("drop", onDrop);
    return () => {
      window.removeEventListener("dragenter", onDragEnter);
      window.removeEventListener("dragover", onDragOver);
      window.removeEventListener("dragleave", onDragLeave);
      window.removeEventListener("drop", onDrop);
    };
  }, [uploadSkillArchive, uploading]);

  return (
    <div className="flex flex-col gap-6">
      {isDragging && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-background/70 backdrop-blur-sm pointer-events-none print:hidden animate-in fade-in duration-150">
          <div className="m-6 flex flex-col items-center gap-4 px-8 py-10 text-foreground text-base font-medium">
            <Files className="size-14 text-foreground/90" />
            Отпустите, чтобы загрузить архив со скиллом
          </div>
        </div>
      )}

      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Скиллы агента</h2>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handleCheckGithubUpdates}
            disabled={uploading || githubUpdatesLoading}
            title="Проверить обновления GitHub-скиллов"
          >
            <RefreshCw
              className={`size-4 mr-1.5 ${githubUpdatesLoading ? "animate-spin" : ""}`}
            />
            {githubUpdatesLoading ? "Проверка..." : "Обновления"}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={handleSyncLocal}
            title="Синхронизировать локальные скиллы"
          >
            <FolderSync className="size-4 mr-1.5" />
            Синхр.
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowBuiltinCatalog(!showBuiltinCatalog)}
          >
            <Zap className="size-4 mr-1.5" />
            Каталог
            {showBuiltinCatalog ? (
              <ChevronUp className="size-3 ml-1" />
            ) : (
              <ChevronDown className="size-3 ml-1" />
            )}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              resetGithubDialog();
              setGithubDialogOpen(true);
            }}
            disabled={uploading}
          >
            <Github className="size-4 mr-1.5" />
            Из GitHub
          </Button>
          <Button
            variant="default"
            size="sm"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
          >
            <Upload className="size-4 mr-1.5" />
            {uploading ? "Загрузка..." : "Загрузить"}
          </Button>
          <input
            ref={fileInputRef}
            type="file"
            className="hidden"
            accept=".zip,.tar.gz,.tgz,.tar.bz2,.tar"
            onChange={handleUpload}
          />
        </div>
      </div>

      {showBuiltinCatalog && builtins.length > 0 && (
        <div className="border border-border rounded-lg p-4 bg-muted/30">
          <h3 className="text-sm font-medium mb-3">Встроенные скиллы</h3>
          <div className="flex flex-col gap-2">
            {builtins.map((b) => (
              <div
                key={b.name}
                className="flex items-center justify-between p-3 rounded-md bg-card border border-border"
              >
                <div className="flex flex-col gap-0.5">
                  <span className="font-medium text-sm">{b.name}</span>
                  <span className="text-xs text-muted-foreground">
                    {b.description}
                  </span>
                </div>
                <Button
                  variant={b.is_installed ? "secondary" : "default"}
                  size="sm"
                  disabled={b.is_installed}
                  onClick={() => handleInstallBuiltin(b.name)}
                >
                  {b.is_installed ? (
                    "Установлен"
                  ) : (
                    <>
                      <Download className="size-3 mr-1" />
                      Установить
                    </>
                  )}
                </Button>
              </div>
            ))}
          </div>
        </div>
      )}

      {loading ? (
        <div className="text-center text-muted-foreground py-8">
          Загрузка...
        </div>
      ) : skills.length === 0 ? (
        <div className="text-center text-muted-foreground py-12 border border-dashed border-border rounded-lg">
          <Zap className="size-8 mx-auto mb-3 opacity-40" />
          <p className="text-sm">Нет установленных скиллов</p>
          <p className="text-xs mt-1">
            Загрузите архив со скиллом или установите встроенный из каталога
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {skills.map((skill) => (
            <SkillItem
              key={skill.id}
              skill={skill}
              onToggle={handleToggle}
              onDelete={handleDelete}
              onView={handleView}
              githubUpdate={githubUpdates[skill.id]}
              onUpdateGithub={handleGithubUpdate}
              disabled={uploading || githubUpdatesLoading}
            />
          ))}
        </div>
      )}

      <Dialog open={viewDialogOpen} onOpenChange={setViewDialogOpen}>
        <DialogContent className="max-w-2xl max-h-[80vh] overflow-auto">
          <DialogHeader>
            <DialogTitle>{viewDetail?.skill.name}</DialogTitle>
            <DialogDescription>
              {viewDetail?.skill.description}
            </DialogDescription>
          </DialogHeader>
          {viewDetail?.body ? (
            <pre className="text-sm whitespace-pre-wrap bg-muted/50 rounded-lg p-4 overflow-auto max-h-[50vh]">
              {viewDetail.body}
            </pre>
          ) : (
            <p className="text-sm text-muted-foreground">
              Содержимое SKILL.md недоступно
            </p>
          )}
        </DialogContent>
      </Dialog>

      <Dialog
        open={githubDialogOpen}
        onOpenChange={(open) => {
          setGithubDialogOpen(open);
          if (!open) resetGithubDialog();
        }}
      >
        <DialogContent
          className={`sm:max-w-3xl overflow-hidden ${
            githubPreview
              ? "h-[80vh] max-h-[80vh] flex flex-col gap-4"
              : "h-auto"
          }`}
        >
          <DialogHeader>
            <DialogTitle>Установить скиллы из GitHub</DialogTitle>
            <DialogDescription>
              Поддерживаются публичные GitHub-репозитории и ссылки на каталоги
              со SKILL.md.
            </DialogDescription>
          </DialogHeader>

          <div className="flex flex-col gap-3">
            <div className="flex gap-2">
              <Input
                value={githubSource}
                onChange={(event) => setGithubSource(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !githubPreviewLoading) {
                    void handleGithubPreview();
                  }
                }}
                placeholder="vercel-labs/agent-skills или https://github.com/..."
                disabled={githubPreviewLoading || githubInstalling}
              />
              <Button
                variant="outline"
                onClick={handleGithubPreview}
                disabled={githubPreviewLoading || githubInstalling}
              >
                <Search className="size-4 mr-1.5" />
                {githubPreviewLoading ? "Поиск..." : "Найти"}
              </Button>
            </div>
          </div>

          {githubPreview && (
            <div className="flex min-h-0 flex-1 flex-col gap-3">
              <div className="flex shrink-0 flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <Badge variant="outline">{githubPreview.source}</Badge>
              </div>

              {githubPreview.warnings.length > 0 && (
                <div className="shrink-0 rounded-md border border-yellow-500/40 bg-yellow-500/10 p-3 text-xs">
                  <div className="font-medium mb-1">
                    Некоторые пути пропущены
                  </div>
                  {githubPreview.warnings.map((warning) => (
                    <div key={warning}>{warning}</div>
                  ))}
                </div>
              )}

              <div className="grid min-h-0 flex-1 grid-cols-1 gap-2 overflow-y-auto pr-1 lg:grid-cols-2">
                {githubPreview.skills.map((skill) => {
                  const selected = githubSelected[skill.path] === true;
                  const isUpdate =
                    skill.already_installed &&
                    skill.installed_commit !== githubPreview.commit;
                  const isSameCommit = skill.already_installed && !isUpdate;
                  return (
                    <label
                      key={skill.path}
                      className={`flex cursor-pointer items-center gap-3 rounded-lg border p-3 transition-colors ${selected ? "border-primary bg-primary/5" : "border-border"}`}
                    >
                      <input
                        type="checkbox"
                        className="sr-only"
                        checked={selected}
                        onChange={(event) => {
                          const checked = event.target.checked;
                          setGithubSelected((previous) => ({
                            ...previous,
                            [skill.path]: checked,
                          }));
                          if (checked && skill.already_installed) {
                            setGithubReplace((previous) => ({
                              ...previous,
                              [skill.path]: true,
                            }));
                          }
                        }}
                        disabled={githubInstalling}
                      />
                      <span
                        aria-hidden="true"
                        className="pointer-events-none flex size-3.5 shrink-0 items-center justify-center text-white"
                      >
                        {selected && <CheckIcon className="size-4" />}
                      </span>
                      <div className="flex min-w-0 flex-1 flex-col gap-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-medium">{skill.name}</span>
                          {isSameCommit && (
                            <Badge variant="secondary" className="text-xs">
                              Уже установлен
                            </Badge>
                          )}
                          {isUpdate && (
                            <Badge variant="outline" className="text-xs">
                              <RefreshCw className="size-3 mr-1" />
                              Доступно обновление
                            </Badge>
                          )}
                        </div>
                        <code className="text-xs text-muted-foreground break-all">
                          {skill.path || "."}
                        </code>
                        <a
                          href={skill.manifest_url}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex w-fit items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
                          onClick={(event) => event.stopPropagation()}
                        >
                          <ExternalLink className="size-3" />
                          Открыть SKILL.md на GitHub
                        </a>
                      </div>
                    </label>
                  );
                })}
              </div>

              {githubResults.length > 0 && (
                <div className="flex flex-col gap-1 rounded-md border border-border p-3 text-sm">
                  <div className="font-medium">Результат установки</div>
                  {githubResults.map((result) => (
                    <div key={result.path} className="flex items-start gap-2">
                      {result.status === "error" ? (
                        <AlertCircle className="mt-0.5 size-4 text-destructive shrink-0" />
                      ) : (
                        <CheckCircle2 className="mt-0.5 size-4 text-green-500 shrink-0" />
                      )}
                      <span>
                        {result.name}:{" "}
                        {result.status === "error"
                          ? result.error
                          : result.status}
                      </span>
                    </div>
                  ))}
                </div>
              )}

              <div className="flex shrink-0 justify-end gap-2 border-t border-border pt-3">
                <Button
                  variant="outline"
                  onClick={() => setGithubDialogOpen(false)}
                  disabled={githubInstalling}
                >
                  Закрыть
                </Button>
                <Button
                  onClick={handleGithubInstall}
                  disabled={githubInstalling || githubPreviewLoading}
                >
                  <Download className="size-4 mr-1.5" />
                  {githubInstalling ? "Установка..." : "Установить выбранные"}
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
};
