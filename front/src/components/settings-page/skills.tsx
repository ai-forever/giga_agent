import React, { useState, useEffect, useCallback, useRef } from "react";
import {
  Plus,
  Trash2,
  Upload,
  Download,
  ToggleLeft,
  ToggleRight,
  ChevronDown,
  ChevronUp,
  Zap,
  FileText,
  FolderSync,
  Files,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
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
  created_at: string;
  is_readonly?: boolean;
  can_toggle?: boolean;
}

interface BuiltinSkillInfo {
  name: string;
  description: string;
  is_installed: boolean;
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
};

const SkillItem: React.FC<{
  skill: SkillSummary;
  onToggle: (id: string, enabled: boolean) => void;
  onDelete: (id: string) => void;
  onView: (id: string) => void;
  disabled?: boolean;
}> = ({ skill, onToggle, onDelete, onView, disabled }) => {
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
        </div>
        {skill.description && (
          <span className="text-sm text-muted-foreground line-clamp-2">
            {skill.description}
          </span>
        )}
      </div>
      <div className="flex items-center gap-1 shrink-0">
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
          <Button
            variant="ghost"
            size="icon"
            onClick={() => onToggle(skill.id, !skill.is_enabled)}
            title={skill.is_enabled ? "Отключить" : "Включить"}
            disabled={disabled}
          >
            {skill.is_enabled ? (
              <ToggleRight className="size-4 text-green-500" />
            ) : (
              <ToggleLeft className="size-4 text-muted-foreground" />
            )}
          </Button>
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
              disabled={uploading}
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
    </div>
  );
};
