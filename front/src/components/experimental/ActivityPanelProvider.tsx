import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import type { Activity } from "@/interfaces";
import { getActivity } from "./api";
import ActivityDrawer from "./ActivityDrawer";

interface ActivityPanelCtx {
  /** Открыта ли панель сейчас (для toggle-поведения триггеров). */
  isOpen: boolean;
  /** Открыть панель со встроенным снапшотом (завершённый маркер). */
  openActivity: (activity: Activity) => void;
  /** Открыть панель с живым поллингом активности треда (активный ран). */
  openForThread: (threadId: string) => void;
  close: () => void;
}

const noop: ActivityPanelCtx = {
  isOpen: false,
  openActivity: () => {},
  openForThread: () => {},
  close: () => {},
};

const Ctx = createContext<ActivityPanelCtx | null>(null);

// Вне провайдера (обычный режим) — no-op, чтобы виджеты не падали.
export const useActivityPanel = (): ActivityPanelCtx => useContext(Ctx) ?? noop;

const LIVE_POLL_MS = 2500;

export const ActivityPanelProvider: React.FC<{
  children: React.ReactNode;
}> = ({ children }) => {
  const [open, setOpen] = useState(false);
  const [activity, setActivity] = useState<Activity | null>(null);
  const [liveThreadId, setLiveThreadId] = useState<string | null>(null);

  const openActivity = useCallback((a: Activity) => {
    setLiveThreadId(null);
    setActivity(a);
    setOpen(true);
  }, []);

  const openForThread = useCallback((threadId: string) => {
    setActivity(null);
    setLiveThreadId(threadId);
    setOpen(true);
  }, []);

  const close = useCallback(() => {
    setOpen(false);
    setLiveThreadId(null);
  }, []);

  // Живой поллинг активности, пока панель открыта в live-режиме.
  useEffect(() => {
    if (!open || !liveThreadId) return;
    let cancelled = false;
    let controller: AbortController | null = null;
    const tick = async () => {
      controller?.abort();
      controller = new AbortController();
      try {
        const a = await getActivity(liveThreadId, {
          signal: controller.signal,
        });
        if (cancelled) return;
        // Ран завершился → кэш очищен, ручка отдаёт пустышку. Не затираем
        // последний хороший снимок пустым — панель замирает на финальном состоянии.
        const empty = (a.items?.length ?? 0) === 0 && a.started_at == null;
        setActivity((prev) =>
          empty && prev && (prev.items?.length ?? 0) > 0 ? prev : a,
        );
      } catch {
        /* сетевые сбои поллинга игнорируем */
      }
    };
    void tick();
    const id = window.setInterval(() => void tick(), LIVE_POLL_MS);
    return () => {
      cancelled = true;
      controller?.abort();
      window.clearInterval(id);
    };
  }, [open, liveThreadId]);

  return (
    <Ctx.Provider value={{ isOpen: open, openActivity, openForThread, close }}>
      {/* Панель сдвигает контент чата (как основной сайдбар — margin + transition),
          а не перекрывает его. На узких экранах drawer перекрывает поверх. */}
      <div
        className={[
          "flex grow flex-col min-h-0 w-full transition-[margin] duration-200 ease-in-out",
          open ? "min-[900px]:mr-[420px]" : "min-[900px]:mr-0",
          "print:!mr-0",
        ].join(" ")}
      >
        {children}
      </div>
      <ActivityDrawer open={open} activity={activity} onClose={close} />
    </Ctx.Provider>
  );
};

export default ActivityPanelProvider;
