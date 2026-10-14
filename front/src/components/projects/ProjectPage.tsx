import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { ArrowLeft, MessageSquarePlus, Trash2 } from "lucide-react";
import type { Thread } from "@langchain/langgraph-sdk";
import { Client } from "@langchain/langgraph-sdk";

import { ApiError } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
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
import { useAuth } from "@/components/providers/auth.tsx";
import { API_BASE_URL } from "@/config.ts";
import { useExperimentalMode } from "@/hooks/useExperimentalMode.ts";
import { refreshThreads } from "@/lib/events";

import { deleteProject, getProject, Project, updateProject } from "./api";
import KnowledgeSection from "./KnowledgeSection";

const errorDetail = (e: unknown, fallback: string): string => {
  if (e instanceof ApiError) return e.message || fallback;
  if (e instanceof Error) return e.message || fallback;
  return fallback;
};

const ProjectPage: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const { token } = useAuth();
  const { experimentalActive } = useExperimentalMode();
  // graph_id проектных чатов — совпадает с projectGraphId в Sidebar: в
  // experimental-режиме проекты работают с обёрткой giga_agent_experimental.
  const projectGraphId = experimentalActive
    ? "giga_agent_experimental"
    : "giga_agent";

  const [project, setProject] = useState<Project | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [instructions, setInstructions] = useState("");
  const [saving, setSaving] = useState(false);

  const [threads, setThreads] = useState<Thread[]>([]);
  const [threadsLoading, setThreadsLoading] = useState(false);

  const langGraphClient = useMemo(() => {
    if (!token) return null;
    return new Client({
      apiUrl: API_BASE_URL,
      apiKey: token,
      defaultHeaders: { Authorization: `Bearer ${token}` },
    });
  }, [token]);

  const loadProject = useCallback(
    async (signal?: AbortSignal) => {
      if (!projectId) return;
      setLoading(true);
      setLoadError(null);
      try {
        const p = await getProject(projectId, { signal });
        setProject(p);
        setName(p.name);
        setDescription(p.description ?? "");
        setInstructions(p.instructions ?? "");
      } catch (e) {
        if (signal?.aborted) return;
        setLoadError(errorDetail(e, "Не удалось загрузить проект"));
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    },
    [projectId],
  );

  const loadThreads = useCallback(
    async (signal?: AbortSignal) => {
      if (!projectId || !langGraphClient) return;
      setThreadsLoading(true);
      try {
        const result = await langGraphClient.threads.search({
          // См. projectGraphId: в experimental-режиме показываем только
          // экспериментальные треды проекта, иначе — обычные.
          metadata: { project_id: projectId, graph_id: projectGraphId },
          limit: 50,
          sortBy: "updated_at",
          sortOrder: "desc",
          signal,
        });
        setThreads(
          result.filter(
            (thread) =>
              (thread.metadata as Record<string, unknown> | undefined)
                ?.subagent !== true,
          ),
        );
      } catch (e) {
        if (signal?.aborted) return;
        console.error("Failed to load project threads", e);
      } finally {
        if (!signal?.aborted) setThreadsLoading(false);
      }
    },
    [projectId, langGraphClient, projectGraphId],
  );

  useEffect(() => {
    const ctrl = new AbortController();
    void loadProject(ctrl.signal);
    return () => ctrl.abort();
  }, [loadProject]);

  useEffect(() => {
    const ctrl = new AbortController();
    void loadThreads(ctrl.signal);
    return () => ctrl.abort();
  }, [loadThreads]);

  const dirty = useMemo(() => {
    if (!project) return false;
    return (
      name !== project.name ||
      description !== (project.description ?? "") ||
      instructions !== (project.instructions ?? "")
    );
  }, [project, name, description, instructions]);

  const save = async () => {
    if (!project) return;
    if (!name.trim()) {
      toast.error("Название не может быть пустым");
      return;
    }
    setSaving(true);
    try {
      const updated = await updateProject(project.id, {
        name: name.trim(),
        description: description.trim() || null,
        instructions: instructions.trim() || null,
      });
      setProject(updated);
      toast.success("Проект сохранён");
    } catch (e) {
      toast.error("Не удалось сохранить", {
        description: errorDetail(e, "Попробуйте ещё раз."),
      });
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!project) return;
    try {
      await deleteProject(project.id);
      // Просигналить сайдбару перезагрузить список проектов (и треды
      // раскрытых проектов), иначе удалённый проект висит в списке до
      // полной перезагрузки страницы.
      refreshThreads();
      toast.success("Проект удалён");
      navigate("/");
    } catch (e) {
      toast.error("Не удалось удалить", {
        description: errorDetail(e, "Попробуйте ещё раз."),
      });
    }
  };

  const startNewChat = async () => {
    if (!project || !langGraphClient) return;
    try {
      const t = await langGraphClient.threads.create({
        metadata: {
          project_id: project.id,
          // В experimental-режиме сайдбар/чат работают с обёрткой
          // giga_agent_experimental — проектный тред должен нести тот же
          // graph_id, иначе он не подхватится (и kickoff не перенесёт
          // project_id на скрытый inner-тред giga_agent).
          graph_id: projectGraphId,
        },
      });
      refreshThreads();
      navigate(`/threads/${t.thread_id}`);
    } catch (e) {
      toast.error("Не удалось создать чат", {
        description: errorDetail(e, "Попробуйте ещё раз."),
      });
    }
  };

  if (loading) {
    return (
      <div className="flex-1 p-6 text-muted-foreground">Загрузка проекта…</div>
    );
  }

  if (loadError || !project) {
    return (
      <div className="flex-1 p-6">
        <div className="text-red-500 mb-3">
          {loadError ?? "Проект не найден"}
        </div>
        <Button variant="outline" onClick={() => navigate("/")}>
          <ArrowLeft className="w-4 h-4 mr-2" />
          На главную
        </Button>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-3xl mx-auto p-6 flex flex-col gap-6">
        <div className="flex items-center justify-between gap-3">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => navigate("/")}
            className="-ml-2"
            style={{ zIndex: 100 }}
          >
            <ArrowLeft className="w-4 h-4 mr-1" />
            Назад
          </Button>
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button
                variant="ghost"
                size="sm"
                style={{ zIndex: 100 }}
                className="text-red-500"
              >
                <Trash2 className="w-4 h-4 mr-1" />
                Удалить
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Удалить проект?</AlertDialogTitle>
                <AlertDialogDescription>
                  Чаты, привязанные к проекту, останутся, но потеряют связь.
                  Действие нельзя отменить.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Отмена</AlertDialogCancel>
                <AlertDialogAction
                  onClick={handleDelete}
                  className="bg-red-500 hover:bg-red-600"
                >
                  Удалить
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </div>

        <Card>
          <CardContent className="p-5 flex flex-col gap-4">
            <div className="flex flex-col gap-1">
              <label className="text-xs uppercase text-muted-foreground">
                Название
              </label>
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Название проекта"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs uppercase text-muted-foreground">
                Описание
              </label>
              <Input
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Краткое описание (опционально)"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs uppercase text-muted-foreground">
                Инструкции для агента
              </label>
              <Textarea
                value={instructions}
                onChange={(e) => setInstructions(e.target.value)}
                placeholder="Эти инструкции будут добавляться к системному промпту во всех чатах проекта."
                className="min-h-[200px] font-mono text-sm"
              />
            </div>
            <div className="flex justify-end">
              <Button onClick={save} disabled={!dirty || saving}>
                {saving ? "Сохранение…" : "Сохранить"}
              </Button>
            </div>
          </CardContent>
        </Card>

        <KnowledgeSection collectionId={project.collection_id} />

        <div className="flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <div className="text-sm font-medium">
              Чаты в проекте {threads.length > 0 && `(${threads.length})`}
            </div>
            <Button size="sm" onClick={startNewChat}>
              <MessageSquarePlus className="w-4 h-4 mr-1" />
              Новый чат
            </Button>
          </div>
          {threadsLoading ? (
            <div className="text-sm text-muted-foreground">Загрузка чатов…</div>
          ) : threads.length === 0 ? (
            <div className="text-sm text-muted-foreground">
              Пока ни одного чата. Создайте первый.
            </div>
          ) : (
            <div className="flex flex-col gap-1">
              {threads.map((t) => {
                const title =
                  (t.metadata?.thread_title as string | undefined) ??
                  "Без названия";
                return (
                  <div
                    key={t.thread_id}
                    onClick={() => navigate(`/threads/${t.thread_id}`)}
                    className="px-3 py-2 rounded-lg hover:bg-muted cursor-pointer text-sm truncate"
                  >
                    {title}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default ProjectPage;
