import React, { useCallback, useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { ArrowDown } from "lucide-react";
import MessageList from "./MessageList";
import InputArea from "./InputArea";
import { GraphState } from "../interfaces";
import { Link, useNavigate, useParams } from "react-router-dom";
import { uiMessageReducer } from "@langchain/langgraph-sdk/react-ui";
import { SelectedAttachmentsProvider } from "../hooks/SelectedAttachmentsContext.tsx";
import { useStream, UseStream } from "@langchain/langgraph-sdk/react";
import { Client } from "@langchain/langgraph-sdk";
import { persistStoppedAiMessage } from "@/lib/stopped-message.ts";
import { useAuth } from "@/components/providers/auth.tsx";
import { API_BASE_URL, EXPERIMENTAL_MODE } from "@/config.ts";
import { refreshThreads } from "@/lib/events";
import {
  hideThrowingThreadGetters,
  suppressPhantomBreakpointInterrupt,
} from "@/lib/thread-history";
import { BranchesProvider } from "@/hooks/useBranches";
import { ActivityPanelProvider } from "@/components/experimental/ActivityPanelProvider";
import type { PromptSuggestionScenario } from "@/types/prompt-suggestions";

interface ChatProps {
  onThreadIdChange?: (threadId: string) => void;
  onThreadReady?: (thread: UseStream<GraphState>) => void;
  onRequestReload?: () => void;
  /** Граф/ассистент, к которому подключается стрим. По умолчанию основной агент. */
  assistantId?: string;
}

const Chat: React.FC<ChatProps> = ({
  onThreadIdChange,
  onThreadReady,
  onRequestReload,
  assistantId = "giga_agent",
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
    assistantId,
    messagesKey: "messages",
    reconnectOnMount: true,
    threadId: threadId === undefined ? null : threadId,
    fetchStateHistory: false,
    throttle: 10,
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
    // После стопа в values может остаться interrupt отменённого рана —
    // гасим его, чтобы не показывался approve-UI (mutate мержит поверхностно,
    // поэтому пустой массив, а не удаление ключа).
    // Заодно помечаем AI-сообщения rendered: «печатная машинка» в Message.tsx
    // допечатывает буфер с задержками и без этого продолжает «стримить» текст
    // после остановки; rendered заставляет дорисовать хвост мгновенно.
    onStop: ({ mutate }) => {
      mutate((prev) => {
        const messages = (prev.messages ?? []).map((m) =>
          m.type === "ai" &&
          !(m.additional_kwargs as Record<string, unknown> | undefined)
            ?.rendered
            ? {
                ...m,
                additional_kwargs: { ...m.additional_kwargs, rendered: true },
              }
            : m,
        );
        // Частичный AI-ответ сохраняем именно отсюда: prev — самые свежие
        // values стрима (то, что на экране); снимок в обработчике клика
        // отстаёт на чанки, прилетевшие за время отмены. Вызов идемпотентен:
        // persistStoppedAiMessage не пишет, если сообщение уже в чекпоинте.
        const tail = messages.at(-1);
        if (tail?.type === "ai" && threadId) {
          void persistStoppedAiMessage(
            threadRef.current.client as unknown as Client,
            threadId,
            tail,
          );
        }
        return { ...prev, __interrupt__: [], messages };
      });
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
    suggestion: PromptSuggestionScenario;
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
  const localStreamRef = useRef<{
    wasLoading: boolean;
    finishedAt: number;
    messagesLength: number;
    lastMessageId: string | null;
  }>({
    wasLoading: false,
    finishedAt: 0,
    messagesLength: 0,
    lastMessageId: null,
  });

  useEffect(() => {
    const isLoading = Boolean(thread.isLoading);
    const lastMessage = stableMessages.at(-1) as any;
    if (localStreamRef.current.wasLoading && !isLoading) {
      localStreamRef.current = {
        wasLoading: false,
        finishedAt: Date.now(),
        messagesLength: stableMessages.length,
        lastMessageId: lastMessage?.id ?? null,
      };
      return;
    }

    localStreamRef.current = {
      ...localStreamRef.current,
      wasLoading: isLoading,
    };
  }, [thread.isLoading, stableMessages]);

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
          const localStream = localStreamRef.current;
          const currentLastMessageId =
            ((threadRef.current.messages?.at(-1) as any)?.id as
              | string
              | undefined) ?? null;
          const isLocalStreamReplay =
            localStream.finishedAt > 0 &&
            Math.abs(localStream.finishedAt - finishedAt) < 15000 &&
            localStream.messagesLength === threadRef.current.messages.length &&
            localStream.lastMessageId === currentLastMessageId;
          // The local stream already merged this run into state; replaying it
          // would only toggle SDK loading state and rerender the message list.
          if (isLocalStreamReplay) {
            return;
          }
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

  // Конец рана (стрим закрылся): aegra финализирует тред в idle до закрытия
  // SSE (run_executor: finalize_run → _signal_end_event), поэтому сразу
  // обновляем сайдбар — индикатор активного треда гаснет, не дожидаясь
  // 20-секундного поллинга.
  const prevRunActiveRef = useRef(thread.isLoading);
  useEffect(() => {
    if (prevRunActiveRef.current && !thread.isLoading) {
      refreshThreads();
    }
    prevRunActiveRef.current = thread.isLoading;
  }, [thread.isLoading]);

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
    <ActivityPanelProvider>
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
          {EXPERIMENTAL_MODE && (thread.values as any)?.inner_thread_id && (
            <Link
              to={`/dev/threads/${(thread.values as any).inner_thread_id}`}
              target="_blank"
              rel="noreferrer"
              title="Открыть оригинальный тред giga_agent (dev)"
              className="self-end mr-2 mt-1 text-xs text-muted-foreground/70 underline hover:text-foreground print:hidden z-1000"
            >
              dev: оригинальный тред ↗
            </Link>
          )}
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
                  onSelectSuggestion={(suggestion) =>
                    setPrefillPayload({ suggestion, nonce: Date.now() })
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
    </ActivityPanelProvider>
  );
};

export default Chat;
