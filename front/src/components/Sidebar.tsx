import React, { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  ChevronRight,
  Plus,
  Files,
  Settings as SettingsIcon,
  Brain,
  User,
  LogOut,
  Shield,
  MoreHorizontal,
  Pencil,
  Trash2,
  Loader2,
} from "lucide-react";
import GigaChainLogo from "../assets/gigachain_logo.svg";
import { useSettings } from "./Settings.tsx";
import { API_BASE_URL, ragEnabled } from "@/config.ts";
import { useTheme, ThemeMode } from "@/components/providers/theme.tsx";
import { useAuth } from "@/components/providers/auth.tsx";
import { Client } from "@langchain/langgraph-sdk";
import type { Thread } from "@langchain/langgraph-sdk";
import { appEvents, refreshThreads, THREADS_REFRESH_EVENT } from "@/lib/events";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
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
import DarkLogoSvg from "../assets/dark_theme_GigaAgent.svg?react";
import LightLogoSvg from "../assets/light_theme_GigaAgent.svg?react";

interface SidebarProps {
  onNewChat: () => void;
}

const SidebarComponent = ({ onNewChat }: SidebarProps) => {
  const navigate = useNavigate();
  const location = useLocation();
  const { settings, setSettings } = useSettings();
  const { isDark } = useTheme();
  const { user, logout, token } = useAuth();
  const THREADS_PAGE_SIZE = 50;
  const SIDEBAR_WIDTH = 270;

  const activeThreadId = useMemo(() => {
    const match = location.pathname.match(/^\/threads\/([^/?#]+)/);
    return match ? decodeURIComponent(match[1]) : null;
  }, [location.pathname]);

  const langGraphClient = useMemo(() => {
    if (!token) return null;
    return new Client({
      apiUrl: API_BASE_URL,
      apiKey: token,
      defaultHeaders: {
        Authorization: `Bearer ${token}`,
      },
    });
  }, [token]);

  const [threads, setThreads] = useState<Thread[]>([]);
  const [threadsLoading, setThreadsLoading] = useState(false);
  const [threadsLoadingMore, setThreadsLoadingMore] = useState(false);
  const [threadsError, setThreadsError] = useState<string | null>(null);
  const [threadsMoreError, setThreadsMoreError] = useState<string | null>(null);
  const [threadsTotal, setThreadsTotal] = useState<number | null>(null);
  const [threadsHasMore, setThreadsHasMore] = useState(false);
  const [threadsRefreshTick, setThreadsRefreshTick] = useState(0);
  const [typedTitles, setTypedTitles] = useState<Record<string, string>>({});
  const typingTimersRef = useRef<Record<string, number>>({});
  const prevThreadsRef = useRef<Map<string, string>>(new Map());
  const hasLoadedThreadsOnceRef = useRef(false);
  const loadMoreControllerRef = useRef<AbortController | null>(null);

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

  useEffect(() => {
    const onRefresh = () => setThreadsRefreshTick((x) => x + 1);
    appEvents.addEventListener(THREADS_REFRESH_EVENT, onRefresh);
    return () =>
      appEvents.removeEventListener(THREADS_REFRESH_EVENT, onRefresh);
  }, []);

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
      select: ["thread_id", "metadata"],
      metadata: {
        graph_id: "giga_agent",
      },
      limit: THREADS_PAGE_SIZE,
      offset: 0,
      sortBy: "updated_at",
      sortOrder: "desc",
      signal: controller.signal,
    });

    const countPromise = langGraphClient.threads.count({
      metadata: {
        graph_id: "giga_agent",
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
            const lastIdPart = t.thread_id.split("/").filter(Boolean).at(-1);
            const shortId = (lastIdPart ?? t.thread_id).slice(0, 4);
            const displayTitle =
              rawTitle.length > 0 ? rawTitle : `Новый чат - ${shortId}`;
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
        select: ["thread_id", "metadata"],
        metadata: {
          graph_id: "giga_agent",
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

  const handleOpenThread = (threadId: string) => {
    closeSidebarOnMobile();
    navigate(`/threads/${threadId}`);
  };

  const [renameOpen, setRenameOpen] = useState(false);
  const [renameSaving, setRenameSaving] = useState(false);
  const [renameError, setRenameError] = useState<string | null>(null);
  const [renameThread, setRenameThread] = useState<Thread | null>(null);
  const [renameValue, setRenameValue] = useState("");

  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteSaving, setDeleteSaving] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [deleteThread, setDeleteThread] = useState<Thread | null>(null);

  const getThreadMeta = (t: Thread): Record<string, unknown> => {
    const meta = (t as unknown as { metadata?: Record<string, unknown> })
      .metadata;
    return meta ?? {};
  };

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
        className={[
          "fixed top-0 left-0 h-full p-1 pt-2 z-[11] transition-transform duration-300 ease-in-out print:hidden flex flex-col",
          "bg-background border text-card-foreground",
          settings.sideBarOpen ? "translate-x-0" : "",
        ].join(" ")}
        style={{
          width: `${SIDEBAR_WIDTH}px`,
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

        {/* Список чатов (LangGraph threads.search / search_threads) */}
        {user && (
          <div className="flex flex-col flex-1 min-h-0">
            <div className="px-2 py-1 text-xs uppercase tracking-wide text-muted-foreground">
              Чаты
            </div>
            {!threadsLoading && threadsError && (
              <div className="px-2 py-1 text-sm text-destructive">
                {threadsError}
              </div>
            )}
            {!threadsLoading && !threadsError && threads.length === 0 && (
              <div className="px-2 py-1 text-sm text-muted-foreground">
                Нет чатов
              </div>
            )}
            <div className="flex-1 min-h-0 overflow-auto">
              {threadsLoading && threads.length === 0 ? (
                <div className="px-2 py-2 space-y-2">
                  {Array.from({ length: 10 }).map((_, i) => (
                    <Skeleton key={i} className="h-9 w-full" />
                  ))}
                </div>
              ) : (
                <>
                  {threads.map((t) => {
                    const fullTitle = getThreadTitle(t);
                    const displayTitle = typedTitles[t.thread_id] ?? fullTitle;
                    const isActive = activeThreadId === t.thread_id;

                    return (
                      <div
                        key={t.thread_id}
                        className={[
                          "group px-2 py-1 text-sm rounded-lg cursor-pointer transition-colors flex items-center gap-2",
                          isActive
                            ? "bg-accent text-accent-foreground border border-border"
                            : "hover:bg-muted/50",
                        ].join(" ")}
                        onClick={() => handleOpenThread(t.thread_id)}
                        title={t.thread_id}
                        aria-current={isActive ? "page" : undefined}
                      >
                        <span className="flex-1 min-w-0 truncate">
                          {displayTitle}
                        </span>
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-8 w-8 opacity-0 group-hover:opacity-100 focus:opacity-100"
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
                          Показано {threads.length} из {threadsTotal}
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
                {ragEnabled() && (
                  <DropdownMenuItem onSelect={handleRag}>
                    <Files className="mr-2 h-4 w-4" />
                    Документы
                  </DropdownMenuItem>
                )}
                <DropdownMenuItem onSelect={handleMemories}>
                  <Brain className="mr-2 h-4 w-4" />
                  Факты о вас
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

      {/* Rename dialog */}
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

      {/* Opener button */}
      {/* <div className="fixed top-4 left-5 z-[200] bg-transparent border-0 flex items-center text-card-foreground transition-[left] duration-300 ease-in-out print:[&>svg]:hidden">
        <div
          className="h-10 bg-cover transition-[width] duration-300 ease-in-out cursor-pointer"
          style={{
            width: settings.sideBarOpen ? 156 : 40,
            backgroundImage: `url(${isDark ? LogoImage : LogoWhiteImage})`,
          }}
          onClick={() => {
            if (window.innerWidth >= 900) {
              handleNewChat();
            }
          }}
        />
        <ChevronRight
          onClick={toggle}
          style={{
            transform: settings.sideBarOpen ? "rotate(180deg)" : "rotate(0)",
            marginLeft: "0.5rem",
          }}
        />
      </div> */}
    </>
  );
};

export default SidebarComponent;
