import React, { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { RefreshCw, Search, Trash2 } from "lucide-react";

import { ApiError } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";

import {
  ABOUT_PATH,
  deleteMemory,
  getMemory,
  getMemoryByPath,
  listMemories,
  MemoryFileSummary,
  updateMemory,
  upsertMemoryByPath,
} from "./api";

const errorDetail = (e: unknown, fallback: string): string => {
  if (e instanceof ApiError) {
    return e.message || fallback;
  }
  if (e instanceof Error) {
    return e.message || fallback;
  }
  return fallback;
};

const AboutTab: React.FC = () => {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [exists, setExists] = useState(false);
  const [content, setContent] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      const file = await getMemoryByPath(ABOUT_PATH, { signal });
      setContent(file.content);
      setExists(true);
    } catch (e) {
      if (signal?.aborted) return;
      if (e instanceof ApiError && e.isNotFound()) {
        setContent("");
        setExists(false);
      } else {
        setError(errorDetail(e, "Не удалось загрузить ABOUT.md"));
      }
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const ctrl = new AbortController();
    void load(ctrl.signal);
    return () => ctrl.abort();
  }, [load]);

  const save = async () => {
    setSaving(true);
    try {
      const file = await upsertMemoryByPath(ABOUT_PATH, content);
      setContent(file.content);
      setExists(true);
      toast.success(exists ? "ABOUT.md сохранён" : "ABOUT.md создан");
    } catch (e) {
      toast.error("Не удалось сохранить", {
        richColors: true,
        description: errorDetail(e, "Попробуйте ещё раз."),
      });
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <div className="text-muted-foreground">Загрузка ABOUT.md…</div>;
  }
  if (error) {
    return <div className="text-red-500">Ошибка: {error}</div>;
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-medium">/memories/ABOUT.md</div>
          <div className="text-xs text-muted-foreground">
            {exists
              ? "Главный файл памяти про вас."
              : "Файл ещё не создан — сохраните, чтобы он появился."}
          </div>
        </div>
        <Button onClick={save} disabled={saving}>
          {saving ? "Сохранение…" : exists ? "Сохранить" : "Создать"}
        </Button>
      </div>
      <Textarea
        value={content}
        onChange={(e) => setContent(e.target.value)}
        placeholder={
          "# ABOUT\n\nЗапишите сюда главное про себя: имя, роль, привычки, контекст работы, стиль общения."
        }
        className="min-h-[420px] font-mono text-sm"
      />
    </div>
  );
};

type EditorState = {
  open: boolean;
  loading: boolean;
  saving: boolean;
  deleting: boolean;
  fileId: string | null;
  path: string;
  content: string;
  error: string | null;
};

const initialEditorState: EditorState = {
  open: false,
  loading: false,
  saving: false,
  deleting: false,
  fileId: null,
  path: "",
  content: "",
  error: null,
};

const formatDate = (value: string | null): string => {
  if (!value) return "—";
  try {
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return value;
    return d.toLocaleString();
  } catch {
    return value;
  }
};

const FilesTab: React.FC = () => {
  const [items, setItems] = useState<MemoryFileSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [editor, setEditor] = useState<EditorState>(initialEditorState);

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      const data = await listMemories(undefined, { signal });
      setItems(data);
    } catch (e) {
      if (signal?.aborted) return;
      setError(errorDetail(e, "Не удалось загрузить список"));
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const ctrl = new AbortController();
    void load(ctrl.signal);
    return () => ctrl.abort();
  }, [load]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter((it) => {
      const desc = (it.description || "").toLowerCase();
      const path = it.path.toLowerCase();
      return path.includes(q) || desc.includes(q);
    });
  }, [items, query]);

  const openEditor = async (summary: MemoryFileSummary) => {
    setEditor({
      ...initialEditorState,
      open: true,
      loading: true,
      fileId: summary.id,
      path: summary.path,
    });
    try {
      const file = await getMemory(summary.id);
      setEditor((prev) => ({
        ...prev,
        loading: false,
        path: file.path,
        content: file.content,
      }));
    } catch (e) {
      setEditor((prev) => ({
        ...prev,
        loading: false,
        error: errorDetail(e, "Не удалось загрузить файл"),
      }));
    }
  };

  const closeEditor = () => setEditor(initialEditorState);

  const saveEditor = async () => {
    if (!editor.fileId) return;
    setEditor((prev) => ({ ...prev, saving: true, error: null }));
    try {
      await updateMemory(editor.fileId, editor.content);
      toast.success("Файл памяти сохранён");
      closeEditor();
      void load();
    } catch (e) {
      setEditor((prev) => ({
        ...prev,
        saving: false,
        error: errorDetail(e, "Не удалось сохранить файл"),
      }));
    }
  };

  const deleteEditor = async () => {
    if (!editor.fileId) return;
    setEditor((prev) => ({ ...prev, deleting: true, error: null }));
    try {
      await deleteMemory(editor.fileId);
      toast.success("Файл памяти удалён");
      closeEditor();
      void load();
    } catch (e) {
      setEditor((prev) => ({
        ...prev,
        deleting: false,
        error: errorDetail(e, "Не удалось удалить файл"),
      }));
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[240px]">
          <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Поиск по названию или описанию"
            className="pl-8"
          />
        </div>
        <Button
          variant="outline"
          size="icon"
          onClick={() => void load()}
          disabled={loading}
          title="Обновить"
        >
          <RefreshCw className="h-4 w-4" />
        </Button>
      </div>

      {loading && <div className="text-muted-foreground">Загрузка…</div>}
      {error && !loading && <div className="text-red-500">Ошибка: {error}</div>}
      {!loading && !error && items.length === 0 && (
        <div className="text-muted-foreground">Файлов памяти пока нет.</div>
      )}
      {!loading && !error && items.length > 0 && filtered.length === 0 && (
        <div className="text-muted-foreground">
          Ничего не нашлось по «{query}».
        </div>
      )}

      {!loading && filtered.length > 0 && (
        <ul className="flex flex-col divide-y rounded-md border">
          {filtered.map((it) => (
            <li key={it.id}>
              <button
                type="button"
                onClick={() => void openEditor(it)}
                className="w-full text-left px-4 py-3 hover:bg-accent transition-colors cursor-pointer"
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="font-medium truncate">{it.path}</div>
                  {it.tag && (
                    <span className="text-xs px-2 py-0.5 rounded bg-muted text-muted-foreground shrink-0">
                      {it.tag}
                    </span>
                  )}
                </div>
                <div className="text-sm text-muted-foreground mt-0.5">
                  {it.description || "Без описания"}
                </div>
                <div className="text-xs text-muted-foreground mt-1">
                  Обновлено: {formatDate(it.updated_at)}
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}

      <Dialog
        open={editor.open}
        onOpenChange={(open) => {
          if (!open) closeEditor();
        }}
      >
        <DialogContent className="sm:max-w-4xl max-h-[90vh] flex flex-col overflow-hidden">
          <DialogHeader className="min-w-0">
            <DialogTitle className="font-mono text-base truncate">
              {editor.path}
            </DialogTitle>
            <DialogDescription>
              Редактируйте содержимое файла памяти. Описание задаётся через
              YAML-frontmatter в начале файла.
            </DialogDescription>
          </DialogHeader>

          {editor.loading ? (
            <div className="text-muted-foreground py-6">Загрузка…</div>
          ) : (
            <>
              <Textarea
                value={editor.content}
                onChange={(e) =>
                  setEditor((prev) => ({ ...prev, content: e.target.value }))
                }
                className="min-h-[280px] w-full min-w-0 flex-1 resize-none overflow-auto font-mono text-sm"
              />
              {editor.error && (
                <div className="text-sm text-red-500">{editor.error}</div>
              )}
            </>
          )}

          <DialogFooter className="flex flex-row flex-wrap items-center justify-between gap-2">
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button
                  variant="destructive"
                  disabled={editor.loading || editor.saving || editor.deleting}
                >
                  <Trash2 className="mr-2 h-4 w-4" />
                  Удалить
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Удалить файл памяти?</AlertDialogTitle>
                  <AlertDialogDescription>
                    {editor.path} будет удалён вместе с индексами поиска.
                    Действие необратимо.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Отмена</AlertDialogCancel>
                  <AlertDialogAction
                    onClick={deleteEditor}
                    className="bg-destructive hover:bg-destructive/90 text-white"
                  >
                    Удалить
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>

            <div className="flex gap-2">
              <Button variant="outline" onClick={closeEditor}>
                Отмена
              </Button>
              <Button
                onClick={saveEditor}
                disabled={editor.loading || editor.saving}
              >
                {editor.saving ? "Сохранение…" : "Сохранить"}
              </Button>
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};

const MemoriesPage: React.FC = () => {
  return (
    <div className="container mx-auto bg-card p-5 w-full flex lg:p-5 p-0 lg:mt-0">
      <Card className="max-w-[1000px] w-full mx-auto border-0 shadow-none">
        <CardContent className="flex flex-col space-y-4 px-6 max-[900px]:p-0">
          <div>
            <h1 className="text-xl font-semibold">Факты о вас</h1>
            <p className="text-sm text-muted-foreground">
              То, что агент помнит между диалогами.
            </p>
          </div>

          <Tabs defaultValue="about" className="w-full">
            <TabsList>
              <TabsTrigger value="about">ABOUT.md</TabsTrigger>
              <TabsTrigger value="files">Все файлы</TabsTrigger>
            </TabsList>
            <TabsContent value="about" className="mt-4">
              <AboutTab />
            </TabsContent>
            <TabsContent value="files" className="mt-4">
              <FilesTab />
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>
    </div>
  );
};

export default MemoriesPage;
