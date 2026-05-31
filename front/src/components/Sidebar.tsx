import React, { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  Brain,
  ChevronDown,
  ChevronRight,
  Download,
  Files,
  FolderOpen,
  FolderPlus,
  Loader2,
  LogOut,
  MessageSquarePlus,
  MoreHorizontal,
  Pencil,
  Settings as SettingsIcon,
  Shield,
  Trash2,
  User,
} from "lucide-react";
import GigaChainLogo from "../assets/gigachain_logo.svg";
import { useSettings } from "./Settings.tsx";
import { ragEnabled } from "@/config.ts";
import { useTheme } from "@/components/providers/theme.tsx";
import { useAuth } from "@/components/providers/auth.tsx";
import type { Thread } from "@langchain/langgraph-sdk";
import { useLangGraphClient } from "@/hooks/useLangGraphClient";
import { appEvents, refreshThreads, THREADS_REFRESH_EVENT } from "@/lib/events";
import {
  createProject,
  listProjects,
  Project,
} from "@/components/projects/api";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { exportChat, type ExportFormat } from "@/lib/chat-export";
import { toast } from "sonner";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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
} from "@/components/ui/alert-dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useUserInfo } from "@/components/providers/user-info.tsx";
import TelegramIcon from "../assets/telegram-colored.svg";
import DarkLogoSvg from "../assets/dark_theme_GigaAgent.svg?react";
import LightLogoSvg from "../assets/light_theme_GigaAgent.svg?react";

interface SidebarProps {
  onNewChat: () => void;
}

const LAST_SEEN_STORAGE_KEY = "sidebar_thread_last_seen_v1";
const THREADS_PAGE_SIZE = 50;
const THREADS_POLL_INTERVAL_MS = 20_000;

const readLastSeenFromStorage = (): Record<string, string> => {
  try {
    const raw = localStorage.getItem(LAST_SEEN_STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return {};
    }
    const result: Record<string, string> = {};
    for (const [k, v] of Object.entries(parsed as Record<string, unknown>)) {
      if (typeof v === "string") result[k] = v;
    }
    return result;
  } catch {
    return {};
  }
};

const getThreadStatus = (t: Thread): string | undefined => {
  const s = (t as unknown as { status?: unknown }).status;
  return typeof s === "string" ? s : undefined;
};

const getThreadUpdatedAt = (t: Thread): string | undefined => {
  const u = (t as unknown as { updated_at?: unknown }).updated_at;
  return typeof u === "string" ? u : undefined;
};

const SidebarComponent = ({ onNewChat }: SidebarProps) => {
  const navigate = useNavigate();
  const location = useLocation();
  const { settings, setSettings } = useSettings();
  const { isDark } = useTheme();
  const { user, logout } = useAuth();
  const { openContextModal } = useUserInfo();
  const SIDEBAR_WIDTH = 270;

  const activeThreadId = useMemo(() => {
    const match = location.pathname.match(/^\/threads\/([^/?#]+)/);
    return match ? decodeURIComponent(match[1]) : null;
  }, [location.pathname]);

  const langGraphClient = useLangGraphClient();

  const [threads, setThreads] = useState<Thread[]>([]);
  const [threadsLoading, setThreadsLoading] = useState(false);
  const [threadsLoadingMore, setThreadsLoadingMore] = useState(false);
  const [threadsError, setThreadsError] = useState<string | null>(null);
  const [threadsMoreError, setThreadsMoreError] = useState<string | null>(null);
  const [threadsTotal, setThreadsTotal] = useState<number | null>(null);
  const [threadsHasMore, setThreadsHasMore] = useState(false);
  const [threadsRefreshTick, setThreadsRefreshTick] = useState(0);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectsLoading, setProjectsLoading] = useState(false);
  const [createProjectOpen, setCreateProjectOpen] = useState(false);
  const [createProjectName, setCreateProjectName] = useState("");
  const [createProjectSaving, setCreateProjectSaving] = useState(false);
  const [createProjectError, setCreateProjectError] = useState<string | null>(
    null,
  );
  const [expandedProjects, setExpandedProjects] = useState<Set<string>>(() => {
    try {
      const raw = localStorage.getItem("sidebar_expanded_projects_v1");
      return raw ? new Set(JSON.parse(raw)) : new Set();
    } catch {
      return new Set();
    }
  });
  const [projectThreads, setProjectThreads] = useState<
    Record<string, Thread[]>
  >({});
  const [projectThreadsLoading, setProjectThreadsLoading] = useState<
    Record<string, boolean>
  >({});

  const activeProjectId = useMemo(() => {
    const match = location.pathname.match(/^\/projects\/([^/?#]+)/);
    return match ? decodeURIComponent(match[1]) : null;
  }, [location.pathname]);
  const [typedTitles, setTypedTitles] = useState<Record<string, string>>({});
  const [lastSeen, setLastSeen] = useState<Record<string, string>>(() =>
    readLastSeenFromStorage(),
  );

  useEffect(() => {
    try {
      localStorage.setItem(LAST_SEEN_STORAGE_KEY, JSON.stringify(lastSeen));
    } catch {
      /* storage unavailable — ignore */
    }
  }, [lastSeen]);

  const markThreadSeen = (threadId: string, updatedAt: string | undefined) => {
    if (!updatedAt) return;
    setLastSeen((prev) => {
      if (prev[threadId] === updatedAt) return prev;
      return { ...prev, [threadId]: updatedAt };
    });
  };
  const typingTimersRef = useRef<Record<string, number>>({});
  const prevThreadsRef = useRef<Map<string, string>>(new Map());
  const hasLoadedThreadsOnceRef = useRef(false);
  const loadMoreControllerRef = useRef<AbortController | null>(null);
  const currentGraphId = useMemo(
    () =>
      settings.showChatType === "channels"
        ? "giga_agent_channel"
        : "giga_agent",
    [settings.showChatType],
  );

  const startTypingTitle = (threadId: string, fullTitle: string) => {
    const existingTimer = typingTimersRef.current[threadId];
    if (existingTimer) {
      window.clearInterval(existingTimer);
      delete typingTimersRef.current[threadId];
    }

    // Avoid a "blank" frame: render first character immediately.
    setTypedTitles((prev) => ({ ...prev, [threadId]: fullTitle.slice(0, 1) }));
    let i = 1;
    const timerId = window.setInterval(() => {
      i += 1;
      setTypedTitles((prev) => {
        const next = fullTitle.slice(0, i);
        if (next.length >= fullTitle.length) {
          return { ...prev, [threadId]: fullTitle };
        }
        return { ...prev, [threadId]: next };
      });

      if (i >= fullTitle.length) {
        window.clearInterval(timerId);
        delete typingTimersRef.current[threadId];
      }
    }, 18);
    typingTimersRef.current[threadId] = timerId;
  };

  useEffect(() => {
    return () => {
      for (const id of Object.values(typingTimersRef.current)) {
        window.clearInterval(id);
      }
      typingTimersRef.current = {};
      loadMoreControllerRef.current?.abort();
      loadMoreControllerRef.current = null;
    };
  }, []);

  // Keep the currently-open thread marked as seen at its latest updated_at
  // whenever the sidebar refreshes. If a user is viewing a thread and new
  // activity lands, they see it live — so the dot should never appear on
  // the active thread.
  useEffect(() => {
    if (!activeThreadId) return;
    const active = threads.find((t) => t.thread_id === activeThreadId);
    if (!active) return;
    markThreadSeen(activeThreadId, getThreadUpdatedAt(active));
  }, [activeThreadId, threads]);

  useEffect(() => {
    hasLoadedThreadsOnceRef.current = false;
    prevThreadsRef.current = new Map();
    setTypedTitles({});
    setThreads([]);
    setThreadsError(null);
    setThreadsMoreError(null);
    setThreadsTotal(null);
    setThreadsHasMore(false);
  }, [currentGraphId]);

  useEffect(() => {
    const onRefresh = () => setThreadsRefreshTick((x) => x + 1);
    appEvents.addEventListener(THREADS_REFRESH_EVENT, onRefresh);
    return () =>
      appEvents.removeEventListener(THREADS_REFRESH_EVENT, onRefresh);
  }, []);

  useEffect(() => {
    if (!settings.sideBarOpen || !langGraphClient) return;

    const intervalId = window.setInterval(() => {
      setThreadsRefreshTick((x) => x + 1);
    }, THREADS_POLL_INTERVAL_MS);

    return () => window.clearInterval(intervalId);
  }, [
    currentGraphId,
    langGraphClient,
    settings.sideBarOpen,
    THREADS_POLL_INTERVAL_MS,
  ]);

  useEffect(() => {
    if (!settings.sideBarOpen) return;
    if (!langGraphClient) {
      setThreads([]);
      setThreadsError(null);
      setThreadsMoreError(null);
      setThreadsTotal(null);
      setThreadsHasMore(false);
      setThreadsLoadingMore(false);
      loadMoreControllerRef.current?.abort();
      loadMoreControllerRef.current = null;
      return;
    }

    const controller = new AbortController();
    loadMoreControllerRef.current?.abort();
    loadMoreControllerRef.current = null;
    setThreadsLoadingMore(false);
    setThreadsLoading(true);
    setThreadsError(null);
    setThreadsMoreError(null);

    const searchPromise = langGraphClient.threads.search({
      select: ["thread_id", "metadata", "status", "updated_at"],
      metadata: {
        graph_id: currentGraphId,
      },
      limit: THREADS_PAGE_SIZE,
      offset: 0,
      sortBy: "updated_at",
      sortOrder: "desc",
      signal: controller.signal,
    });

    const countPromise = langGraphClient.threads.count({
      metadata: {
        graph_id: currentGraphId,
      },
      signal: controller.signal,
    });

    void Promise.allSettled([searchPromise, countPromise])
      .then((settled) => {
        const searchSettled = settled[0];
        const countSettled = settled[1];
        if (searchSettled.status === "rejected") {
          throw searchSettled.reason;
        }

        const result = searchSettled.value;
        const total =
          countSettled.status === "fulfilled" ? countSettled.value : null;

        const hasMore =
          total === null
            ? result.length === THREADS_PAGE_SIZE
            : result.length < total;
        // First successful load: show titles immediately (no typing animation).
        if (!hasLoadedThreadsOnceRef.current) {
          const next = new Map<string, string>();
          for (const t of result) {
            const meta = (
              t as unknown as { metadata?: Record<string, unknown> }
            ).metadata;
            const rawTitle =
              typeof meta?.thread_title === "string"
                ? meta.thread_title.trim()
                : "";
            next.set(t.thread_id, rawTitle);
          }
          prevThreadsRef.current = next;
          hasLoadedThreadsOnceRef.current = true;
          // On the first load for this graph, seed lastSeen for any thread we
          // don't have an entry for yet — existing threads shouldn't all light
          // up as unread. Threads that appear on *subsequent* loads stay
          // unseeded, so genuinely-new activity shows a dot.
          setLastSeen((prev) => {
            let changed = false;
            const merged = { ...prev };
            for (const t of result) {
              if (t.thread_id in merged) continue;
              const updatedAt = getThreadUpdatedAt(t);
              if (updatedAt) {
                merged[t.thread_id] = updatedAt;
                changed = true;
              }
            }
            return changed ? merged : prev;
          });
          setThreads(result);
          setThreadsTotal(total);
          setThreadsHasMore(hasMore);
          return;
        }

        // Subsequent loads: detect new threads or newly appeared titles to animate typing.
        const prev = prevThreadsRef.current;
        const next = new Map<string, string>();

        for (const t of result) {
          const meta = (t as unknown as { metadata?: Record<string, unknown> })
            .metadata;
          const rawTitle =
            typeof meta?.thread_title === "string"
              ? meta.thread_title.trim()
              : "";
          next.set(t.thread_id, rawTitle);

          const prevTitle = prev.get(t.thread_id);
          const isNewThread = prevTitle === undefined;
          const titleJustAppeared =
            (prevTitle === undefined || prevTitle.length === 0) &&
            rawTitle.length > 0;

          if (isNewThread || titleJustAppeared) {
            const displayTitle =
              rawTitle.length > 0 ? rawTitle : `Новый диалог`;
            startTypingTitle(t.thread_id, displayTitle);
          }
        }

        prevThreadsRef.current = next;
        setThreads(result);
        setThreadsTotal(total);
        setThreadsHasMore(hasMore);
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        const message =
          err instanceof Error ? err.message : "Не удалось загрузить чаты";
        setThreadsError(message);
        setThreads([]);
        setThreadsTotal(null);
        setThreadsHasMore(false);
      })
      .finally(() => {
        if (controller.signal.aborted) return;
        setThreadsLoading(false);
      });

    return () => controller.abort();
  }, [
    currentGraphId,
    langGraphClient,
    settings.sideBarOpen,
    threadsRefreshTick,
    THREADS_PAGE_SIZE,
  ]);

  const loadMoreThreads = async () => {
    if (!langGraphClient) return;
    if (threadsLoading || threadsLoadingMore) return;
    if (!threadsHasMore) return;

    const controller = new AbortController();
    loadMoreControllerRef.current?.abort();
    loadMoreControllerRef.current = controller;

    setThreadsLoadingMore(true);
    setThreadsMoreError(null);

    try {
      const offset = threads.length;
      const result = await langGraphClient.threads.search({
        select: ["thread_id", "metadata", "status", "updated_at"],
        metadata: {
          graph_id: currentGraphId,
        },
        limit: THREADS_PAGE_SIZE,
        offset,
        sortBy: "updated_at",
        sortOrder: "desc",
        signal: controller.signal,
      });

      if (controller.signal.aborted) return;

      const existingIds = new Set(threads.map((t) => t.thread_id));
      const toAdd = result.filter((t) => !existingIds.has(t.thread_id));

      // Pagination append: never animate typing for older threads.
      setThreads((prev) => [...prev, ...toAdd]);
      setTypedTitles((prev) => {
        const next = { ...prev };
        for (const t of toAdd) {
          const meta = (t as unknown as { metadata?: Record<string, unknown> })
            .metadata;
          const rawTitle =
            typeof meta?.thread_title === "string"
              ? meta.thread_title.trim()
              : "";
          if (rawTitle.length > 0) next[t.thread_id] = rawTitle;
        }
        return next;
      });
      const nextPrev = new Map(prevThreadsRef.current);
      for (const t of toAdd) {
        const meta = (t as unknown as { metadata?: Record<string, unknown> })
          .metadata;
        const rawTitle =
          typeof meta?.thread_title === "string"
            ? meta.thread_title.trim()
            : "";
        nextPrev.set(t.thread_id, rawTitle);
      }
      prevThreadsRef.current = nextPrev;

      // Pagination brings in older threads the user may have never opened.
      // Seed lastSeen so they don't all flash as unread.
      setLastSeen((prev) => {
        let changed = false;
        const merged = { ...prev };
        for (const t of toAdd) {
          if (t.thread_id in merged) continue;
          const updatedAt = getThreadUpdatedAt(t);
          if (updatedAt) {
            merged[t.thread_id] = updatedAt;
            changed = true;
          }
        }
        return changed ? merged : prev;
      });

      if (threadsTotal === null) {
        // Fallback when total is unknown: stop only when page is short.
        setThreadsHasMore(result.length === THREADS_PAGE_SIZE);
      } else {
        setThreadsHasMore(offset + result.length < threadsTotal);
      }
    } catch (err: unknown) {
      if (controller.signal.aborted) return;
      const message =
        err instanceof Error ? err.message : "Не удалось загрузить ещё чаты";
      setThreadsMoreError(message);
    } finally {
      if (controller.signal.aborted) return;
      setThreadsLoadingMore(false);
    }
  };

  const handleShowChatTypeChange = (showChatType: "main" | "channels") => {
    setSettings((prev) => ({ ...prev, showChatType }));
  };

  // Получаем отображаемое имя пользователя (email обрезается)
  const displayName = user?.email
    ? user.email.length > 20
      ? user.email.slice(0, 17) + "..."
      : user.email
    : "";

  const toggle = (e: React.MouseEvent) => {
    e.stopPropagation();
    setSettings({ ...settings, ...{ sideBarOpen: !settings.sideBarOpen } });
  };

  const closeSidebarOnMobile = () => {
    if (window.innerWidth <= 900 && settings.sideBarOpen) {
      setSettings({ ...settings, sideBarOpen: false });
    }
  };

  const handleLogout = () => {
    closeSidebarOnMobile();
    logout();
    navigate("/login");
  };

  const handleProfile = () => {
    // TODO: Реализовать страницу профиля
    closeSidebarOnMobile();
    navigate("/profile");
  };

  const handleDemo = (e: React.MouseEvent) => {
    e.stopPropagation();
    navigate("/demo/settings");
  };

  const handleAdminPanel = (e: Event) => {
    e.stopPropagation();
    closeSidebarOnMobile();
    navigate("/admin-panel/users");
  };

  const handleSettings = () => {
    closeSidebarOnMobile();
    navigate("/settings");
  };

  const handleRag = () => {
    closeSidebarOnMobile();
    navigate("/rag");
  };

  const handleMemories = () => {
    closeSidebarOnMobile();
    navigate("/memories");
  };

  const handleNewChat = () => {
    closeSidebarOnMobile();
    navigate("/");
    onNewChat();
  };

  const reloadProjects = React.useCallback(async (signal?: AbortSignal) => {
    setProjectsLoading(true);
    try {
      const list = await listProjects({ signal });
      setProjects(list);
    } catch (e) {
      if (signal?.aborted) return;
      console.error("Failed to load projects", e);
    } finally {
      if (!signal?.aborted) setProjectsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!user) return;
    const ctrl = new AbortController();
    void reloadProjects(ctrl.signal);
    return () => ctrl.abort();
  }, [user, reloadProjects]);

  const handleOpenProject = (projectId: string) => {
    closeSidebarOnMobile();
    navigate(`/projects/${projectId}`);
  };

  const loadProjectThreads = React.useCallback(
    async (projectId: string) => {
      if (!langGraphClient) return;
      setProjectThreadsLoading((prev) => ({ ...prev, [projectId]: true }));
      try {
        const list = await langGraphClient.threads.search({
          metadata: { project_id: projectId },
          limit: 50,
          sortBy: "updated_at",
          sortOrder: "desc",
        });
        setProjectThreads((prev) => ({ ...prev, [projectId]: list }));
      } catch (e) {
        console.error("Failed to load threads for project", projectId, e);
      } finally {
        setProjectThreadsLoading((prev) => ({ ...prev, [projectId]: false }));
      }
    },
    [langGraphClient],
  );

  const toggleProjectExpanded = (projectId: string) => {
    setExpandedProjects((prev) => {
      const next = new Set(prev);
      const wasOpen = next.has(projectId);
      if (wasOpen) next.delete(projectId);
      else next.add(projectId);
      try {
        localStorage.setItem(
          "sidebar_expanded_projects_v1",
          JSON.stringify(Array.from(next)),
        );
      } catch {
        /* ignore */
      }
      if (!wasOpen && projectThreads[projectId] === undefined) {
        void loadProjectThreads(projectId);
      }
      return next;
    });
  };

  // Auto-load threads for any project that's already expanded but has no
  // data yet (e.g., on first paint when expansion came from localStorage).
  useEffect(() => {
    if (!langGraphClient) return;
    for (const projectId of expandedProjects) {
      if (projectThreads[projectId] === undefined) {
        void loadProjectThreads(projectId);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [expandedProjects, langGraphClient, loadProjectThreads]);

  // Refresh open project threads when something elsewhere (e.g., new chat
  // from a project page, project deletion) signals a refresh.
  useEffect(() => {
    const handler = () => {
      for (const projectId of expandedProjects) {
        void loadProjectThreads(projectId);
      }
    };
    appEvents.addEventListener(THREADS_REFRESH_EVENT, handler);
    return () => appEvents.removeEventListener(THREADS_REFRESH_EVENT, handler);
  }, [expandedProjects, loadProjectThreads]);

  const handleNewChatInProject = async (projectId: string) => {
    if (!langGraphClient) return;
    closeSidebarOnMobile();
    try {
      const t = await langGraphClient.threads.create({
        metadata: { project_id: projectId, graph_id: "giga_agent" },
      });
      // Optimistically prepend so the chat appears under the project right away.
      setProjectThreads((prev) => {
        const existing = prev[projectId] ?? [];
        return { ...prev, [projectId]: [t as Thread, ...existing] };
      });
      setExpandedProjects((prev) => {
        if (prev.has(projectId)) return prev;
        const next = new Set(prev).add(projectId);
        try {
          localStorage.setItem(
            "sidebar_expanded_projects_v1",
            JSON.stringify(Array.from(next)),
          );
        } catch {
          /* ignore */
        }
        return next;
      });
      navigate(`/threads/${t.thread_id}`);
    } catch (e) {
      console.error("Failed to create chat in project", e);
    }
  };

  const submitCreateProject = async () => {
    const name = createProjectName.trim();
    if (!name) {
      setCreateProjectError("Введите название");
      return;
    }
    setCreateProjectSaving(true);
    setCreateProjectError(null);
    try {
      const created = await createProject({ name });
      setProjects((prev) => [created, ...prev]);
      setCreateProjectOpen(false);
      setCreateProjectName("");
      navigate(`/projects/${created.id}`);
    } catch (e: unknown) {
      const message =
        e instanceof Error ? e.message : "Не удалось создать проект";
      setCreateProjectError(message);
    } finally {
      setCreateProjectSaving(false);
    }
  };

  const handleOpenThread = (threadId: string) => {
    closeSidebarOnMobile();
    const opened = threads.find((t) => t.thread_id === threadId);
    markThreadSeen(threadId, getThreadUpdatedAt(opened ?? ({} as Thread)));
    navigate(`/threads/${threadId}`);
  };

  const [renameOpen, setRenameOpen] = useState(false);
  const [renameSaving, setRenameSaving] = useState(false);
  const [renameError, setRenameError] = useState<string | null>(null);
  const [renameThread, setRenameThread] = useState<Thread | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [chatSettingsOpen, setChatSettingsOpen] = useState(false);

  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteSaving, setDeleteSaving] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [deleteThread, setDeleteThread] = useState<Thread | null>(null);

  const getThreadMeta = (t: Thread): Record<string, unknown> => {
    const meta = (t as unknown as { metadata?: Record<string, unknown> })
      .metadata;
    return meta ?? {};
  };

  // Threads that belong to a project are shown under their project, not in
  // the main "Чаты" list — same as Claude.
  const visibleThreads = useMemo(
    () => threads.filter((t) => !getThreadMeta(t).project_id),
    [threads],
  );

  const getThreadTitle = (t: Thread): string => {
    const meta = getThreadMeta(t);
    const rawTitle =
      typeof meta.thread_title === "string" ? meta.thread_title.trim() : "";
    const lastIdPart = t.thread_id.split("/").filter(Boolean).at(-1);
    const shortId = (lastIdPart ?? t.thread_id).slice(0, 4);
    return rawTitle.length > 0 ? rawTitle : `Новый чат - ${shortId}`;
  };

  const openRename = (t: Thread) => {
    setRenameThread(t);
    setRenameValue(getThreadTitle(t));
    setRenameError(null);
    setRenameOpen(true);
  };

  const submitRename = async () => {
    const thread = renameThread;
    const title = renameValue.trim();
    if (!thread) return;
    if (!langGraphClient) return;

    if (title.length === 0) {
      setRenameError("Название не может быть пустым");
      return;
    }

    setRenameSaving(true);
    setRenameError(null);
    try {
      const meta = getThreadMeta(thread);
      await langGraphClient.threads.update(thread.thread_id, {
        metadata: {
          ...meta,
          thread_title: title,
        },
      });

      setTypedTitles((prev) => ({ ...prev, [thread.thread_id]: title }));
      refreshThreads();
      setRenameOpen(false);
      setRenameThread(null);
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Не удалось переименовать чат";
      setRenameError(message);
    } finally {
      setRenameSaving(false);
    }
  };

  const openDelete = (t: Thread) => {
    setDeleteThread(t);
    setDeleteError(null);
    setDeleteOpen(true);
  };

  const submitDelete = async () => {
    const thread = deleteThread;
    if (!thread) return;
    if (!langGraphClient) return;

    setDeleteSaving(true);
    setDeleteError(null);
    try {
      await langGraphClient.threads.delete(thread.thread_id);
      if (activeThreadId === thread.thread_id) {
        navigate("/");
      }
      refreshThreads();
      setDeleteOpen(false);
      setDeleteThread(null);
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Не удалось удалить чат";
      setDeleteError(message);
    } finally {
      setDeleteSaving(false);
    }
  };

  const handleThreadExport = async (t: Thread, format: ExportFormat) => {
    if (!langGraphClient) return;
    const toastId = toast.loading("Экспорт чата...");
    try {
      const state = await langGraphClient.threads.getState(t.thread_id);
      const messages = (state.values as any)?.messages;
      if (!messages?.length) {
        toast.dismiss(toastId);
        return;
      }
      const title = getThreadTitle(t);
      await exportChat(messages, format, title);
      toast.success("Экспорт завершён", { id: toastId });
    } catch {
      toast.error("Не удалось выполнить экспорт", { id: toastId });
    }
  };

  const LogoComponent = isDark ? DarkLogoSvg : LightLogoSvg;

  return (
    <>
      {/* Overlay (только мобильные) */}
      {settings.sideBarOpen && (
        <div
          onClick={(e) => {
            const clickX = (e as React.MouseEvent).clientX;
            const targetEl = e.target as HTMLElement;

            if (
              clickX < SIDEBAR_WIDTH ||
              targetEl.closest('[role="menu"]') !== null
            )
              return;

            toggle(e);
          }}
          className={[
            "fixed top-0 left-0 h-full w-full bg-black/50 z-10 print:hidden max-[900px]:block min-[901px]:hidden transition-opacity duration-300 ease-in-out",
            settings.sideBarOpen
              ? "opacity-100 pointer-events-auto"
              : "opacity-0 pointer-events-none",
          ].join(" ")}
        />
      )}
      <div
        className={[
          "sticky max-[900px]:bg-card min-[900px]:fixed align-middle items-center p-4 top-0 w-full h-[60px] flex transition-[margin] duration-300 ease-in-out",
          settings.sideBarOpen ? "min-[900px]:ml-[270px]" : "",
        ].join(" ")}
      >
        <LogoComponent
          className="hidden print:block h-20 w-[150px]"
          preserveAspectRatio="xMidYMin meet"
          aria-label="GigaAgent Logo"
        />
        <ChevronRight
          onClick={toggle}
          className="print:hidden"
          style={{
            transform: settings.sideBarOpen ? "rotate(180deg)" : "rotate(0)",
            marginLeft: "0.5rem",
            cursor: "pointer",
          }}
        />
      </div>

      {/* Sidebar */}
      <div
        data-onboarding="sidebar"
        className={[
          "fixed top-0 left-0 h-full p-1 pt-2 z-[11] transition-transform duration-300 ease-in-out print:hidden flex flex-col",
          "bg-background border text-card-foreground",
          settings.sideBarOpen ? "translate-x-0" : "",
        ].join(" ")}
        style={{
          width: `${SIDEBAR_WIDTH}px`,
          borderTop: 0,
          transform: settings.sideBarOpen
            ? undefined
            : `translateX(-${SIDEBAR_WIDTH + 10}px)`,
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          className="flex items-center p-2 text-sm rounded-lg cursor-pointer hover:bg-muted/50"
          onClick={handleNewChat}
        >
          <img
            src={GigaChainLogo}
            alt="GigaChain"
            className="w-7 h-7 mr-2 mt-[1px]"
          />
          Новый чат
        </div>

        <hr className="my-3 border-border/60" />

        {ragEnabled() && (
          <div
            className={[
              "flex items-center p-2 text-sm rounded-lg cursor-pointer hover:bg-muted/50",
              location.pathname === "/rag"
                ? "bg-accent text-accent-foreground"
                : "",
            ].join(" ")}
            onClick={handleRag}
          >
            <Files size={20} className="mr-2" />
            Документы
          </div>
        )}

        <hr className="my-3 border-border/60" />

        {user && (
          <div className="flex flex-col">
            <div className="flex items-center justify-between gap-2 px-2 py-1">
              <div className="text-xs uppercase tracking-wide text-muted-foreground">
                Проекты
              </div>
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6 text-muted-foreground"
                onClick={() => {
                  setCreateProjectName("");
                  setCreateProjectError(null);
                  setCreateProjectOpen(true);
                }}
                aria-label="Создать проект"
              >
                <FolderPlus className="h-4 w-4" />
              </Button>
            </div>
            {projectsLoading && projects.length === 0 ? (
              <div className="px-2 py-1 text-sm text-muted-foreground">
                Загрузка…
              </div>
            ) : projects.length === 0 ? (
              <div className="px-2 py-1 text-xs text-muted-foreground">
                Нет проектов
              </div>
            ) : (
              projects.map((p) => {
                const isActive = activeProjectId === p.id;
                const isExpanded = expandedProjects.has(p.id);
                const childThreads = projectThreads[p.id] ?? [];
                const childLoading = projectThreadsLoading[p.id] ?? false;
                return (
                  <div key={p.id}>
                    <div
                      className={[
                        "group flex items-center gap-1 pl-1 pr-1 py-1 h-8 text-sm rounded-lg hover:bg-muted/50",
                        isActive ? "bg-accent text-accent-foreground" : "",
                      ].join(" ")}
                    >
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          toggleProjectExpanded(p.id);
                        }}
                        className="h-5 w-5 flex items-center justify-center text-muted-foreground hover:text-foreground shrink-0"
                        aria-label={isExpanded ? "Свернуть" : "Развернуть"}
                      >
                        {isExpanded ? (
                          <ChevronDown className="h-3.5 w-3.5" />
                        ) : (
                          <ChevronRight className="h-3.5 w-3.5" />
                        )}
                      </button>
                      <div
                        onClick={() => handleOpenProject(p.id)}
                        className="flex items-center gap-2 flex-1 min-w-0 cursor-pointer"
                      >
                        <FolderOpen className="h-4 w-4 shrink-0 text-muted-foreground" />
                        <span className="flex-1 min-w-0 truncate">
                          {p.name}
                        </span>
                      </div>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          void handleNewChatInProject(p.id);
                        }}
                        className="h-6 w-6 flex items-center justify-center text-muted-foreground hover:text-foreground opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
                        aria-label="Новый чат в проекте"
                        title="Новый чат"
                      >
                        <MessageSquarePlus className="h-3.5 w-3.5" />
                      </button>
                    </div>
                    {isExpanded && (
                      <div className="ml-5 pl-2 border-l border-border/40 flex flex-col">
                        {childLoading && childThreads.length === 0 ? (
                          <div className="px-2 py-1 text-xs text-muted-foreground">
                            Загрузка…
                          </div>
                        ) : childThreads.length === 0 ? (
                          <div className="px-2 py-1 text-xs text-muted-foreground">
                            Пока пусто
                          </div>
                        ) : (
                          childThreads.map((t) => {
                            const title = getThreadTitle(t);
                            const isActiveThread =
                              activeThreadId === t.thread_id;
                            return (
                              <div
                                key={t.thread_id}
                                onClick={() => handleOpenThread(t.thread_id)}
                                className={[
                                  "px-2 py-1 h-7 text-xs rounded-lg cursor-pointer truncate hover:bg-muted/50",
                                  isActiveThread
                                    ? "bg-accent text-accent-foreground"
                                    : "",
                                ].join(" ")}
                              >
                                {title}
                              </div>
                            );
                          })
                        )}
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </div>
        )}

        <hr className="my-3 border-border/60" />

        {/* Список чатов (LangGraph threads.search / search_threads) */}
        {user && (
          <div className="flex flex-col flex-1 min-h-0">
            <div className="flex items-center justify-between gap-2 px-2 py-1">
              <div className="text-xs uppercase tracking-wide text-muted-foreground">
                Чаты
                {settings.showChatType === "channels" ? " (Каналы)" : ""}
              </div>
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6 text-muted-foreground"
                onClick={() => setChatSettingsOpen(true)}
                aria-label="Настройка чатов"
              >
                <MoreHorizontal className="h-4 w-4" />
              </Button>
            </div>
            {!threadsLoading && threadsError && (
              <div className="px-2 py-1 text-sm text-destructive">
                {threadsError}
              </div>
            )}
            {!threadsLoading && !threadsError && visibleThreads.length === 0 && (
              <div className="px-2 py-1 text-sm text-muted-foreground">
                Нет чатов
              </div>
            )}
            <div className="flex-1 min-h-0 overflow-auto">
              {threadsLoading && visibleThreads.length === 0 ? (
                <div className="px-2 py-2 space-y-2">
                  {Array.from({ length: 10 }).map((_, i) => (
                    <Skeleton key={i} className="h-9 w-full" />
                  ))}
                </div>
              ) : (
                <>
                  {visibleThreads.map((t) => {
                    const fullTitle = getThreadTitle(t);
                    const displayTitle = typedTitles[t.thread_id] ?? fullTitle;
                    const isActive = activeThreadId === t.thread_id;
                    const meta = getThreadMeta(t);
                    const isTelegramThread = meta.channel === "telegram";
                    const status = getThreadStatus(t);
                    const updatedAt = getThreadUpdatedAt(t);
                    const seenAt = lastSeen[t.thread_id];
                    const isUnseen =
                      typeof updatedAt === "string" &&
                      (seenAt === undefined || updatedAt > seenAt);
                    const needsInput =
                      !isActive && status === "interrupted" && isUnseen;
                    const hasUpdate = !isActive && !needsInput && isUnseen;
                    const indicatorTitle = needsInput
                      ? "Ожидает вашего ответа"
                      : hasUpdate
                        ? "Новое обновление"
                        : undefined;

                    return (
                      <div
                        key={t.thread_id}
                        className={[
                          "group relative px-2 py-1 h-10 text-sm rounded-lg cursor-pointer transition-colors flex items-center gap-2",
                          isActive
                            ? "bg-accent text-accent-foreground border border-border"
                            : "hover:bg-muted/50",
                        ].join(" ")}
                        onClick={() => handleOpenThread(t.thread_id)}
                        title={t.thread_id}
                        aria-current={isActive ? "page" : undefined}
                      >
                        {isTelegramThread && (
                          <span title="Telegram" aria-label="Telegram">
                            <img
                              src={TelegramIcon}
                              alt=""
                              className="h-5 w-5 shrink-0"
                            />
                          </span>
                        )}
                        {(needsInput || hasUpdate) && (
                          <span
                            className="shrink-0 flex items-center justify-center"
                            title={indicatorTitle}
                            aria-label={indicatorTitle}
                          >
                            <span
                              className={[
                                "inline-block h-2 w-2 rounded-full",
                                needsInput
                                  ? "bg-amber-500 animate-pulse"
                                  : "bg-sky-500",
                              ].join(" ")}
                            />
                          </span>
                        )}
                        <span
                          className={[
                            "flex-1 min-w-0 truncate transition-[padding]",
                            "group-hover:pr-8 group-focus-within:pr-8",
                            needsInput || hasUpdate ? "font-medium" : "",
                          ].join(" ")}
                        >
                          {displayTitle}
                        </span>
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="absolute right-1 h-8 w-8 opacity-0 pointer-events-none transition-opacity group-hover:opacity-100 group-hover:pointer-events-auto focus:opacity-100 focus:pointer-events-auto data-[state=open]:opacity-100 data-[state=open]:pointer-events-auto"
                              onClick={(e) => e.stopPropagation()}
                              aria-label="Действия чата"
                            >
                              <MoreHorizontal className="h-4 w-4" />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent
                            align="end"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <DropdownMenuItem onSelect={() => openRename(t)}>
                              <Pencil className="mr-2 h-4 w-4" />
                              Переименовать
                            </DropdownMenuItem>
                            <DropdownMenuSub>
                              <DropdownMenuSubTrigger>
                                <Download className="mr-2 h-4 w-4" />
                                Скачать
                              </DropdownMenuSubTrigger>
                              <DropdownMenuSubContent>
                                <DropdownMenuItem
                                  onSelect={() => handleThreadExport(t, "pdf")}
                                >
                                  PDF
                                </DropdownMenuItem>
                                <DropdownMenuItem
                                  onSelect={() => handleThreadExport(t, "docx")}
                                >
                                  DOCX
                                </DropdownMenuItem>
                                <DropdownMenuItem
                                  onSelect={() => handleThreadExport(t, "md")}
                                >
                                  Markdown
                                </DropdownMenuItem>
                              </DropdownMenuSubContent>
                            </DropdownMenuSub>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem
                              className="text-destructive focus:text-destructive"
                              onSelect={() => openDelete(t)}
                            >
                              <Trash2 className="mr-2 h-4 w-4" />
                              Удалить
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </div>
                    );
                  })}

                  {threadsMoreError && (
                    <div className="px-2 py-2 text-sm text-destructive">
                      {threadsMoreError}
                    </div>
                  )}

                  {!threadsLoading && !threadsError && threadsHasMore && (
                    <div className="px-2 py-2">
                      <Button
                        variant="outline"
                        className="w-full"
                        disabled={threadsLoadingMore}
                        onClick={() => void loadMoreThreads()}
                      >
                        {threadsLoadingMore ? (
                          <>
                            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                            Загрузка…
                          </>
                        ) : (
                          "Загрузить ещё"
                        )}
                      </Button>
                      {threadsTotal !== null && (
                        <div className="mt-1 text-xs text-muted-foreground text-center">
                          Показано {visibleThreads.length} из {threadsTotal}
                        </div>
                      )}
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        )}

        {/* <div
          className="flex items-center p-2 text-sm rounded-lg cursor-pointer hover:bg-white/10"
          onClick={handleDemo}
        >
          <SettingsIcon size={24} className="mr-2" />
          Настройки демо
        </div> */}
        {/* Меню пользователя */}
        {user && (
          <div className="pt-3">
            <hr className="mb-3 border-border/60" />
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <div className="flex items-center p-2 text-sm rounded-lg cursor-pointer hover:bg-accent/50 border border-border">
                  <div className="flex items-center justify-center w-8 h-8 rounded-full bg-primary/10 mr-2">
                    <User size={18} className="text-primary" />
                  </div>
                  <span className="truncate">{displayName}</span>
                </div>
              </DropdownMenuTrigger>
              <DropdownMenuContent
                align="start"
                side="top"
                className="w-[200px]"
              >
                {/* <DropdownMenuItem onSelect={handleProfile}>
                  <User className="mr-2 h-4 w-4" />
                  Профиль
                </DropdownMenuItem> */}
                <DropdownMenuItem onSelect={handleMemories}>
                  <Brain className="mr-2 h-4 w-4" />
                  Факты о вас
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => openContextModal()}>
                  <Brain className="mr-2 h-4 w-4" />
                  Персонализация
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={handleSettings}>
                  <SettingsIcon className="mr-2 h-4 w-4" />
                  Настройки
                </DropdownMenuItem>
                {user.is_superuser && (
                  <>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem onSelect={handleAdminPanel}>
                      <Shield className="mr-2 h-4 w-4" />
                      Админ панель
                    </DropdownMenuItem>
                  </>
                )}
                <DropdownMenuSeparator />
                <DropdownMenuItem onSelect={handleLogout}>
                  <LogOut className="mr-2 h-4 w-4 text-destructive" />
                  Выход
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        )}
      </div>

      <Dialog open={chatSettingsOpen} onOpenChange={setChatSettingsOpen}>
        <DialogContent onClick={(e) => e.stopPropagation()}>
          <DialogHeader>
            <DialogTitle>Настройка чатов</DialogTitle>
            <DialogDescription>
              Выберите, какие чаты показывать в боковой панели.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-3">
            <Select
              value={settings.showChatType}
              onValueChange={(value: "main" | "channels") =>
                handleShowChatTypeChange(value)
              }
            >
              <SelectTrigger className="w-full">
                <SelectValue placeholder="Выберите тип чатов" />
              </SelectTrigger>
              <SelectContent className="z-[300]">
                <SelectItem value="main">Основные</SelectItem>
                <SelectItem value="channels">Из каналов</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setChatSettingsOpen(false)}
            >
              Закрыть
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Rename dialog */}
      <Dialog
        open={createProjectOpen}
        onOpenChange={(open) => {
          if (createProjectSaving) return;
          setCreateProjectOpen(open);
          if (!open) {
            setCreateProjectName("");
            setCreateProjectError(null);
          }
        }}
      >
        <DialogContent
          onClick={(e) => e.stopPropagation()}
          onOpenAutoFocus={(e) => e.preventDefault()}
        >
          <DialogHeader>
            <DialogTitle>Новый проект</DialogTitle>
            <DialogDescription>
              Проекты группируют чаты и задают общие инструкции для агента.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Input
              value={createProjectName}
              onChange={(e) => setCreateProjectName(e.target.value)}
              placeholder="Название проекта"
              autoFocus
              onKeyDown={(e) => {
                if (e.key === "Enter") void submitCreateProject();
              }}
              aria-invalid={Boolean(createProjectError) || undefined}
            />
            {createProjectError && (
              <div className="text-sm text-destructive">
                {createProjectError}
              </div>
            )}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setCreateProjectOpen(false)}
              disabled={createProjectSaving}
            >
              Отмена
            </Button>
            <Button
              onClick={() => void submitCreateProject()}
              disabled={createProjectSaving}
            >
              {createProjectSaving ? "Создание…" : "Создать"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={renameOpen}
        onOpenChange={(open) => {
          if (renameSaving) return;
          setRenameOpen(open);
          if (!open) {
            setRenameThread(null);
            setRenameError(null);
          }
        }}
      >
        <DialogContent
          onClick={(e) => e.stopPropagation()}
          onOpenAutoFocus={(e) => e.preventDefault()}
        >
          <DialogHeader>
            <DialogTitle>Переименовать чат</DialogTitle>
            <DialogDescription>
              Новое название будет отображаться в списке чатов.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Input
              value={renameValue}
              onChange={(e) => setRenameValue(e.target.value)}
              autoFocus
              onKeyDown={(e) => {
                if (e.key === "Enter") void submitRename();
              }}
              aria-invalid={Boolean(renameError) || undefined}
            />
            {renameError && (
              <div className="text-sm text-destructive">{renameError}</div>
            )}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setRenameOpen(false)}
              disabled={renameSaving}
            >
              Отмена
            </Button>
            <Button onClick={() => void submitRename()} disabled={renameSaving}>
              Сохранить
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete confirm */}
      <AlertDialog
        open={deleteOpen}
        onOpenChange={(open) => {
          if (deleteSaving) return;
          setDeleteOpen(open);
          if (!open) {
            setDeleteThread(null);
            setDeleteError(null);
          }
        }}
      >
        <AlertDialogContent onClick={(e) => e.stopPropagation()}>
          <AlertDialogHeader>
            <AlertDialogTitle>Удалить чат?</AlertDialogTitle>
            <AlertDialogDescription>
              Это действие нельзя отменить. История диалога будет удалена.
            </AlertDialogDescription>
          </AlertDialogHeader>
          {deleteError && (
            <div className="text-sm text-destructive">{deleteError}</div>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleteSaving}>
              Отмена
            </AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-white hover:bg-destructive/90"
              onClick={(e) => {
                e.preventDefault();
                void submitDelete();
              }}
              disabled={deleteSaving}
            >
              Удалить
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
};

export default SidebarComponent;
