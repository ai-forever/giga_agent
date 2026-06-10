import React, { useCallback, useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { ArrowDown } from "lucide-react";
import MessageList from "./MessageList";
import InputArea from "./InputArea";
import { GraphState } from "../interfaces";
import { useNavigate, useParams } from "react-router-dom";
import { uiMessageReducer } from "@langchain/langgraph-sdk/react-ui";
import { SelectedAttachmentsProvider } from "../hooks/SelectedAttachmentsContext.tsx";
import { useStream, UseStream } from "@langchain/langgraph-sdk/react";
import { useAuth } from "@/components/providers/auth.tsx";
import { API_BASE_URL } from "@/config.ts";
import { refreshThreads } from "@/lib/events";
import {
  hideThrowingThreadGetters,
  suppressPhantomBreakpointInterrupt,
} from "@/lib/thread-history";
import { BranchesProvider } from "@/hooks/useBranches";

interface ChatProps {
  onThreadIdChange?: (threadId: string) => void;
  onThreadReady?: (thread: UseStream<GraphState>) => void;
  onRequestReload?: () => void;
}

const Chat: React.FC<ChatProps> = ({
  onThreadIdChange,
  onThreadReady,
  onRequestReload,
}) => {
  const navigate = useNavigate();
  const { threadId } = useParams<{ threadId?: string }>();
  const { token } = useAuth();
  const suppressNextThreadLoadingRef = useRef(false);
  const suppressedThreadIdRef = useRef<string | null>(null);
  const suppressedThreadLoadingStartedRef = useRef(false);
  // Filled by BranchesProvider; lets onCheckpointEvent grow the branch tree
  // incrementally instead of refetching the whole history after each run.
  const checkpointEventRef = useRef<((data: any) => void) | null>(null);
  const thread = useStream<GraphState>({
    apiUrl: `${API_BASE_URL}/`,
    assistantId: "giga_agent",
    messagesKey: "messages",
    reconnectOnMount: true,
    threadId: threadId === undefined ? null : threadId,
    fetchStateHistory: false,
    throttle: 75,
    apiKey: token,
    defaultHeaders: {
      Authorization: `Bearer ${token}`,
    },
    onThreadId: (nextThreadId: string) => {
      suppressNextThreadLoadingRef.current = !threadId;
      suppressedThreadIdRef.current = !threadId ? nextThreadId : null;
      suppressedThreadLoadingStartedRef.current = false;
      onThreadIdChange?.(nextThreadId);
      navigate(`/threads/${nextThreadId}`);
    },
    onCustomEvent: (event, options) => {
      options.mutate((prev) => {
        // @ts-ignore
        const ui = uiMessageReducer(prev.ui ?? [], event);
        return { ...prev, ui };
      });
    },
    onCheckpointEvent: (data) => {
      checkpointEventRef.current?.(data);
    },
  }) as unknown as UseStream<GraphState>;
  hideThrowingThreadGetters(thread);
  suppressPhantomBreakpointInterrupt(thread);
  const containerRef = useRef<HTMLDivElement>(null);
  const scrollRootRef = useRef<HTMLElement | null>(null);
  const autoScrollEnabledRef = useRef<boolean>(true);
  const bottomSentinelRef = useRef<HTMLDivElement>(null);
  const userScrollIntentRef = useRef<boolean>(false);
  const resetIntentTimeoutRef = useRef<number | null>(null);
  const rafIdRef = useRef<number | null>(null);
  const forceNextAutoScrollSmoothRef = useRef<boolean>(false);
  const programmaticSmoothScrollRef = useRef<boolean>(false);
  const isSafariRef = useRef<boolean>(
    typeof navigator !== "undefined" &&
      /safari/i.test(navigator.userAgent) &&
      !/chrome|android/i.test(navigator.userAgent),
  );
  const firstSroll = useRef<boolean>(false);
  const [showScrollBtn, setShowScrollBtn] = useState<boolean>(false);
  const [prefillPayload, setPrefillPayload] = useState<{
    text: string;
    nonce: number;
  } | null>(null);
  const stableMessages = thread.messages;
  // @ts-ignore
  globalThis.messages = thread.messages;

  const resolveScrollRoot = (): HTMLElement | null => {
    const container = containerRef.current;
    if (!container) return null;

    let current: HTMLElement | null = container.parentElement;
    while (current) {
      const style = window.getComputedStyle(current);
      const canScrollY = /(auto|scroll)/.test(style.overflowY);
      if (canScrollY && current.scrollHeight > current.clientHeight) {
        return current;
      }
      current = current.parentElement;
    }

    return document.scrollingElement as HTMLElement | null;
  };

  useEffect(() => {
    scrollRootRef.current = resolveScrollRoot();
  }, [stableMessages.length]);

  useEffect(() => {
    onThreadReady?.(thread);
  }, [thread, onThreadReady]);

  // reconnectOnMount хранит метаданные рана в sessionStorage (изолирован на вкладку),
  // поэтому ни новая вкладка, ни другой браузер/устройство не подхватывают идущий
  // стрим. Опрашиваем сервер: сравниваем последний известный ран с новейшим на
  // сервере и при расхождении присоединяемся к нему через joinStream.
  //
  // joinStream доигрывает события не только активного, но и недавно завершённого
  // рана: aegra держит replay-буфер ~10 мин (Redis TTL) / ~1 ч (in-memory) после
  // финиша, а сообщения мёрджатся по id, так что повторный джойн идемпотентен.
  // Поэтому отдельный getState не нужен — это покрывает и «ран закончился, пока
  // вкладка была в фоне». Если же буфер уже истёк, делаем полный remount.
  const REPLAY_WINDOW_MS = 8 * 60 * 1000; // консервативно меньше Redis TTL (10 мин)
  const threadRef = useRef(thread);
  threadRef.current = thread;
  const onRequestReloadRef = useRef(onRequestReload);
  onRequestReloadRef.current = onRequestReload;
  // Последний ран, который мы уже учли (стримили / приджойнились / он в state).
  const lastSeenRunIdRef = useRef<string | null>(null);
  useEffect(() => {
    if (!threadId) return;
    lastSeenRunIdRef.current = null;
    let cancelled = false;
    let timer: number | null = null;

    const reconcile = async () => {
      // Запрос только в активной вкладке и когда мы сами не стримим.
      if (cancelled || document.hidden || threadRef.current.isLoading) return;
      try {
        const runs = await threadRef.current.client.runs.list(threadId, {
          limit: 1,
        });
        if (cancelled || threadRef.current.isLoading) return;
        const latest = runs[0] as
          | { run_id: string; status: string; updated_at?: string }
          | undefined;
        if (!latest) return;

        const isActive =
          latest.status === "running" || latest.status === "pending";

        // Первая сверка: запоминаем текущий ран. Активный — джойнимся (мы могли
        // открыть тред в новой вкладке во время стрима); завершённый уже в state.
        if (lastSeenRunIdRef.current === null) {
          lastSeenRunIdRef.current = latest.run_id;
          if (isActive) {
            // @ts-ignore joinStream есть в рантайме SDK, но не в типах UseStream
            threadRef.current.joinStream(latest.run_id);
          }
          return;
        }

        // Ран не сменился — ничего нового.
        if (latest.run_id === lastSeenRunIdRef.current) return;

        // Появился новый ран (запущен в другой вкладке / на другом устройстве).
        lastSeenRunIdRef.current = latest.run_id;
        if (isActive) {
          // @ts-ignore joinStream есть в рантайме SDK, но не в типах UseStream
          threadRef.current.joinStream(latest.run_id);
          return;
        }
        // Ран уже завершился. Если replay-буфер ещё жив — доигрываем через join,
        // иначе буфер истёк и сообщения так не получить → полный remount.
        const finishedAt = latest.updated_at
          ? new Date(latest.updated_at).getTime()
          : 0;
        if (finishedAt && Date.now() - finishedAt < REPLAY_WINDOW_MS) {
          // @ts-ignore joinStream есть в рантайме SDK, но не в типах UseStream
          threadRef.current.joinStream(latest.run_id);
        } else {
          onRequestReloadRef.current?.();
        }
      } catch {
        // тред мог ещё не существовать на сервере / сетевая ошибка — игнорируем
      }
    };

    // Таймер тикает всегда, но сам запрос внутри уходит лишь при видимой вкладке.
    const tick = async () => {
      await reconcile();
      if (!cancelled) timer = window.setTimeout(tick, 10000);
    };

    // Как только вкладка становится активной — проверяем сразу, не дожидаясь тика.
    const onVisibilityChange = () => {
      if (!document.hidden) void reconcile();
    };
    document.addEventListener("visibilitychange", onVisibilityChange);

    void tick();
    return () => {
      cancelled = true;
      if (timer !== null) window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [threadId]);

  useEffect(() => {
    if (threadId) {
      onThreadIdChange?.(threadId);
    }
  }, [threadId, onThreadIdChange]);

  // A thread just created here (its first messages are happening now) is flagged
  // by the same refs that suppress its initial loading spinner. For such threads
  // BranchesProvider builds the tree from checkpoint events instead of fetching.
  const isNewThread =
    !!threadId &&
    suppressNextThreadLoadingRef.current &&
    suppressedThreadIdRef.current === threadId;

  const isThreadLoading =
    Boolean(threadId) &&
    thread.isThreadLoading &&
    !(
      suppressNextThreadLoadingRef.current &&
      suppressedThreadIdRef.current === threadId
    );
  const previousThreadLoadingRef = useRef(isThreadLoading);
  const shouldScrollAfterLoadRef = useRef(false);

  const aiCountRef = useRef<{ threadId: string | null; aiCount: number }>({
    threadId: null,
    aiCount: 0,
  });

  useEffect(() => {
    const currentThreadId = threadId ?? null;
    if (!currentThreadId) return;
    if (!stableMessages || stableMessages.length === 0) return;

    const messages = stableMessages as Array<{ type?: string }>;
    let aiCount = 0;
    for (const m of messages) {
      if (m?.type === "ai") aiCount += 1;
    }

    if (aiCountRef.current.threadId !== currentThreadId) {
      aiCountRef.current = { threadId: currentThreadId, aiCount };
      return;
    }

    if (aiCountRef.current.aiCount === 0 && aiCount > 0) {
      refreshThreads();
    }

    aiCountRef.current = { threadId: currentThreadId, aiCount };
  }, [stableMessages, threadId]);

  useEffect(() => {
    if (previousThreadLoadingRef.current && !isThreadLoading) {
      shouldScrollAfterLoadRef.current = true;
    }

    previousThreadLoadingRef.current = isThreadLoading;
  }, [isThreadLoading]);

  useEffect(() => {
    if (
      threadId &&
      suppressNextThreadLoadingRef.current &&
      suppressedThreadIdRef.current === threadId &&
      thread.isThreadLoading
    ) {
      suppressedThreadLoadingStartedRef.current = true;
    }

    if (
      threadId &&
      suppressNextThreadLoadingRef.current &&
      suppressedThreadIdRef.current === threadId &&
      suppressedThreadLoadingStartedRef.current &&
      !thread.isThreadLoading
    ) {
      suppressNextThreadLoadingRef.current = false;
      suppressedThreadIdRef.current = null;
      suppressedThreadLoadingStartedRef.current = false;
    }
  }, [threadId, thread.isThreadLoading]);

  useEffect(() => {
    if (isThreadLoading) return;
    if (!shouldScrollAfterLoadRef.current) return;

    window.setTimeout(() => {
      bottomSentinelRef.current?.scrollIntoView({ block: "end" });

      const current = containerRef.current;
      if (current) {
        current.scrollTop = current.scrollHeight;
      }

      autoScrollEnabledRef.current = true;
      firstSroll.current = true;
      shouldScrollAfterLoadRef.current = false;
    }, 200);
  }, [isThreadLoading, stableMessages.length]);

  // Наблюдаем за «сентинелом» внизу списка, чтобы понять, включать ли авто-скролл
  useEffect(() => {
    const root = scrollRootRef.current;
    const sentinel = bottomSentinelRef.current;
    if (!root || !sentinel) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          // Включаем авто-скролл только при достижении низа
          autoScrollEnabledRef.current = true;
        }
        // Не выключаем авто-скролл на больших рывках контента
      },
      { root, threshold: 0.99 },
    );

    observer.observe(sentinel);
    return () => {
      if (rafIdRef.current !== null) {
        window.cancelAnimationFrame(rafIdRef.current);
        rafIdRef.current = null;
      }
      observer.disconnect();
    };
  }, [stableMessages.length]);

  const maybeAutoScroll = useCallback(() => {
    const el = scrollRootRef.current;
    if (!el) return;
    if (!autoScrollEnabledRef.current) return;
    if (rafIdRef.current !== null) return; // коалесцируем множественные вызовы за кадр
    rafIdRef.current = window.requestAnimationFrame(() => {
      rafIdRef.current = null;
      const current = scrollRootRef.current;
      if (!current) return;
      const shouldJump =
        !forceNextAutoScrollSmoothRef.current &&
        (isSafariRef.current || firstSroll.current);
      forceNextAutoScrollSmoothRef.current = false;
      if (shouldJump) {
        // Safari: избегаем smooth, чтобы не было скачков вверх
        current.scrollTop = current.scrollHeight;
      } else {
        current.scrollTo({ top: current.scrollHeight, behavior: "smooth" });
      }
      firstSroll.current = true;
    });
  }, [stableMessages.length]);

  const markUserScrollIntent = () => {
    userScrollIntentRef.current = true;
    programmaticSmoothScrollRef.current = false;
    if (resetIntentTimeoutRef.current) {
      window.clearTimeout(resetIntentTimeoutRef.current);
    }
    resetIntentTimeoutRef.current = window.setTimeout(() => {
      userScrollIntentRef.current = false;
    }, 300);
  };

  const handleUserScroll = () => {
    const el = scrollRootRef.current;
    if (!el) return;
    const distanceFromBottom =
      el.scrollHeight - (el.scrollTop + el.clientHeight);
    const nearBottom = distanceFromBottom <= 100;
    if (programmaticSmoothScrollRef.current) {
      if (nearBottom) {
        programmaticSmoothScrollRef.current = false;
      }
      setShowScrollBtn(false);
      return;
    }
    if (userScrollIntentRef.current) {
      if (!nearBottom) {
        // Отключаем авто-скролл только если пользователь явно ушёл от низа
        autoScrollEnabledRef.current = false;
      }
    }
    // Кнопка «вниз» появляется, когда пользователь проскроллил больше одного экрана от низа
    setShowScrollBtn(distanceFromBottom > el.clientHeight);
  };

  const scrollToBottom = () => {
    const el = scrollRootRef.current;
    if (!el) return;
    forceNextAutoScrollSmoothRef.current = true;
    programmaticSmoothScrollRef.current = true;
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    autoScrollEnabledRef.current = true;
    setShowScrollBtn(false);
  };

  useEffect(() => {
    const root = scrollRootRef.current;
    if (!root) return;

    const onWheel = () => markUserScrollIntent();
    const onTouchStart = () => markUserScrollIntent();
    const onScroll = () => handleUserScroll();

    root.addEventListener("wheel", onWheel, { passive: true });
    root.addEventListener("touchstart", onTouchStart, { passive: true });
    root.addEventListener("scroll", onScroll, { passive: true });

    return () => {
      root.removeEventListener("wheel", onWheel);
      root.removeEventListener("touchstart", onTouchStart);
      root.removeEventListener("scroll", onScroll);
    };
  }, [stableMessages.length]);

  return (
    <SelectedAttachmentsProvider>
      <BranchesProvider
        thread={thread}
        threadId={threadId}
        isNewThread={isNewThread}
        checkpointEventRef={checkpointEventRef}
      >
        <div
          className={[
            "flex grow flex-col w-full bg-card print:overflow-visible max-[900px]:justify-between",
            !stableMessages.length ? "justify-center" : "",
          ].join(" ")}
          ref={containerRef}
        >
          <div
            className={[
              stableMessages.length || isThreadLoading
                ? "grow flex-1 p-7 max-[900px]:p-0"
                : "",
              "max-w-[900px] w-full  mx-auto flex-col bg-card text-card-foreground rounded-lg max-[900px]:shadow-none max-[900px]:flex-1",
            ].join(" ")}
          >
            {!isThreadLoading && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: 0.2, duration: 0.24, ease: "easeOut" }}
              >
                <MessageList
                  messages={stableMessages ?? []}
                  thread={thread}
                  threadId={threadId}
                  maybeAutoScroll={maybeAutoScroll}
                  onSelectSuggestion={(text) =>
                    setPrefillPayload({ text, nonce: Date.now() })
                  }
                />
              </motion.div>
            )}
          </div>

          {showScrollBtn && stableMessages.length > 0 && (
            <button
              type="button"
              onClick={scrollToBottom}
              title="Прокрутить вниз"
              aria-label="Прокрутить вниз"
              className="sticky bottom-[150px] self-center z-9 flex h-9 w-9 items-center justify-center rounded-full border border-border/60 bg-card/80 py-[10px] text-foreground/80 shadow-[0_2px_10px_rgba(0,0,0,0.08)] transition-all hover:text-foreground hover:shadow-[0_4px_14px_rgba(0,0,0,0.12)] dark:bg-input/80 cursor-pointer print:hidden animate-in fade-in duration-150"
              style={{
                backdropFilter: "blur(2px)",
              }}
            >
              <ArrowDown className="size-4" strokeWidth={1.75} />
            </button>
          )}
          <InputArea
            // @ts-ignore
            thread={thread}
            prefillPayload={prefillPayload}
          />
          <div ref={bottomSentinelRef} style={{ height: 1 }} />
        </div>
      </BranchesProvider>
    </SelectedAttachmentsProvider>
  );
};

export default Chat;
