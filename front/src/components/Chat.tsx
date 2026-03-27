import React, { useEffect, useRef } from "react";
import MessageList from "./MessageList";
import InputArea from "./InputArea";
import { useStableMessages } from "../hooks/useStableMessages";
import { GraphState } from "../interfaces";
import { useNavigate, useParams } from "react-router-dom";
import { uiMessageReducer } from "@langchain/langgraph-sdk/react-ui";
import { SelectedAttachmentsProvider } from "../hooks/SelectedAttachmentsContext.tsx";
import { useStream, UseStream } from "@langchain/langgraph-sdk/react";
import { useAuth } from "@/components/providers/auth.tsx";
import { API_AGENT_PREFIX, API_PREFIX } from "@/config.ts";
import { refreshThreads } from "@/lib/events";
import { useSettings } from "@/components/Settings.tsx";

interface ChatProps {
  onThreadIdChange?: (threadId: string) => void;
  onThreadReady?: (thread: UseStream<GraphState>) => void;
}

const Chat: React.FC<ChatProps> = ({ onThreadIdChange, onThreadReady }) => {
  const navigate = useNavigate();
  const { threadId } = useParams<{ threadId?: string }>();
  const { token } = useAuth();
  const { settings } = useSettings();
  const thread = useStream<GraphState>({
    apiUrl: `${window.location.protocol}//${window.location.host}${API_PREFIX}/`,
    assistantId: "giga_agent",
    messagesKey: "messages",
    reconnectOnMount: true,
    threadId: threadId === undefined ? null : threadId,
    fetchStateHistory: true,
    throttle: 75,
    apiKey: token,
    defaultHeaders: {
      Authorization: `Bearer ${token}`,
    },
    onThreadId: (threadId: string) => {
      onThreadIdChange?.(threadId);
      navigate(`/threads/${threadId}`);
    },
    onCustomEvent: (event, options) => {
      options.mutate((prev) => {
        // @ts-ignore
        const ui = uiMessageReducer(prev.ui ?? [], event);
        return { ...prev, ui };
      });
    },
  });

  const containerRef = useRef<HTMLDivElement>(null);
  const scrollRootRef = useRef<HTMLElement | null>(null);
  const autoScrollEnabledRef = useRef<boolean>(true);
  const bottomSentinelRef = useRef<HTMLDivElement>(null);
  const userScrollIntentRef = useRef<boolean>(false);
  const resetIntentTimeoutRef = useRef<number | null>(null);
  const rafIdRef = useRef<number | null>(null);
  const isSafariRef = useRef<boolean>(
    typeof navigator !== "undefined" &&
      /safari/i.test(navigator.userAgent) &&
      !/chrome|android/i.test(navigator.userAgent),
  );
  const firstSroll = useRef<boolean>(false);
  const stableMessages = useStableMessages(thread);

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
    onThreadReady?.(thread as unknown as UseStream<GraphState>);
  }, [thread, onThreadReady]);

  useEffect(() => {
    if (threadId) {
      onThreadIdChange?.(threadId);
    }
  }, [threadId, onThreadIdChange]);

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

  const maybeAutoScroll = () => {
    const el = scrollRootRef.current;
    if (!el) return;
    if (!autoScrollEnabledRef.current) return;
    if (rafIdRef.current !== null) return; // коалесцируем множественные вызовы за кадр
    rafIdRef.current = window.requestAnimationFrame(() => {
      rafIdRef.current = null;
      const current = scrollRootRef.current;
      if (!current) return;
      if (isSafariRef.current || firstSroll.current) {
        // Safari: избегаем smooth, чтобы не было скачков вверх
        current.scrollTop = current.scrollHeight;
      } else {
        current.scrollTo({ top: current.scrollHeight, behavior: "smooth" });
      }
      firstSroll.current = true;
    });
  };

  const markUserScrollIntent = () => {
    userScrollIntentRef.current = true;
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
    if (!userScrollIntentRef.current) return;
    const nearBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 100;
    if (!nearBottom) {
      // Отключаем авто-скролл только если пользователь явно ушёл от низа
      autoScrollEnabledRef.current = false;
    }
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
      <div
        className={[
          "flex grow flex-col w-full bg-card print:overflow-visible max-[900px]:justify-between",
          !stableMessages.length ? "justify-center" : "",
        ].join(" ")}
        ref={containerRef}
      >
        <div
          className={[
            stableMessages.length ? "grow flex-1 p-7 max-[900px]:p-0" : "",
            "max-w-[900px] w-full  mx-auto flex-col bg-card text-card-foreground rounded-lg max-[900px]:shadow-none",
          ].join(" ")}
        >
          <MessageList
            messages={stableMessages ?? []}
            thread={thread}
            maybeAutoScroll={maybeAutoScroll}
          />
        </div>
        <div ref={bottomSentinelRef} style={{ height: 1 }} />

        <InputArea
          // @ts-ignore
          thread={thread}
        />
      </div>
    </SelectedAttachmentsProvider>
  );
};

export default Chat;
