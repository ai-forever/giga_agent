import React, { useMemo, useRef, useState } from "react";
import { Message as Message_ } from "@langchain/langgraph-sdk";
import type { UseStream } from "@langchain/langgraph-sdk/react";
import { ChevronRight, Loader } from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";

import Message from "./Message.tsx";
import { GraphState, GraphTemplate } from "../interfaces.ts";
import { findScrollRoot } from "@/lib/scroll";

const THINK_TOOL_NAME = "think";

interface AgentRunProps {
  aiMessages: Message_[];
  resultsById: Record<string, Message_>;
  thread?: UseStream<GraphState, GraphTemplate>;
  isLastInThread: boolean;
  maybeAutoScroll: () => void;
  durationStartMessage?: Message_;
  durationEndMessage?: Message_;
  hideFirstMessageContent?: boolean;
  // true, если run появился уже в текущей сессии (а не пришёл из истории
  // при загрузке страницы). Такие — стартуют раскрытыми независимо от
  // мгновенного значения thread.isLoading.
  appearedInSession: boolean;
}

const formatDuration = (ms: number): string | null => {
  if (!isFinite(ms) || ms <= 0) return null;
  const totalSec = Math.round(ms / 1000);
  if (totalSec < 60) return `${totalSec}с`;
  const min = Math.floor(totalSec / 60);
  const sec = totalSec % 60;
  if (min < 60) return sec ? `${min} мин ${sec}с` : `${min} мин`;
  const h = Math.floor(min / 60);
  const restMin = min % 60;
  return restMin ? `${h} ч ${restMin} мин` : `${h} ч`;
};

const getCreatedAt = (
  thread: UseStream<GraphState, GraphTemplate> | undefined,
  message: Message_ | undefined,
): number | null => {
  if (!thread || !message) return null;
  try {
    const meta = thread.getMessagesMetadata(message);
    const createdAt = meta?.firstSeenState?.created_at;
    if (!createdAt) return null;
    const t = Date.parse(createdAt);
    return Number.isFinite(t) ? t : null;
  } catch {
    return null;
  }
};

const AgentRun: React.FC<AgentRunProps> = ({
  aiMessages,
  resultsById,
  thread,
  isLastInThread,
  maybeAutoScroll,
  durationStartMessage,
  durationEndMessage,
  hideFirstMessageContent = false,
  appearedInSession,
}) => {
  const inFlight = !!thread?.isLoading && isLastInThread;

  // На монтировании: раскрыт, если прогон появился в текущей сессии
  // (live стриминг или просто что-то новое в треде); свёрнут только для
  // рунов, загруженных из истории при открытии страницы.
  const [expanded, setExpanded] = useState<boolean>(
    appearedInSession || inFlight,
  );

  const rootRef = useRef<HTMLDivElement>(null);
  const lastBodyHeightRef = useRef<number | null>(null);

  const handleBodyUpdate = (latest: { height?: number | string }) => {
    if (typeof latest.height !== "number") return;
    const prev = lastBodyHeightRef.current;
    if (prev != null) {
      const delta = latest.height - prev;
      if (Math.abs(delta) > 0.25) {
        const root = findScrollRoot(rootRef.current);
        if (root) root.scrollTop += delta;
      }
    }
    lastBodyHeightRef.current = latest.height;
  };

  const resetHeightTracking = () => {
    lastBodyHeightRef.current = null;
  };

  const allToolCalls = useMemo(() => {
    const calls: { name: string; args: any; id?: string; message: Message_ }[] =
      [];
    for (const m of aiMessages) {
      const tc = ((m as any).tool_calls ?? []) as any[];
      for (const c of tc) {
        if (c.name !== THINK_TOOL_NAME) calls.push({ ...c, message: m });
      }
    }
    return calls;
  }, [aiMessages]);

  const duration: string | null = useMemo(() => {
    if (inFlight) return null;
    const startMs = getCreatedAt(thread, durationStartMessage);
    const endMs = getCreatedAt(thread, durationEndMessage);
    if (startMs == null || endMs == null) return null;
    return formatDuration(Math.abs(endMs - startMs));
  }, [durationEndMessage, durationStartMessage, inFlight, thread]);

  const actionsWord =
    allToolCalls.length === 1
      ? "действие"
      : allToolCalls.length >= 2 && allToolCalls.length <= 4
        ? "действия"
        : "действий";

  const headerLabel = inFlight
    ? "Агент работает"
    : duration
      ? `Агент работал · ${duration}`
      : `Агент работал · ${allToolCalls.length} ${actionsWord}`;

  // В развёрнутом теле показываем все шаги текущего agent run.
  const visibleAiMessages = aiMessages;
  const lastVisibleAiMessage = visibleAiMessages.at(-1);

  const toggle = () => setExpanded((v) => !v);

  return (
    <div ref={rootRef} className="my-2.5">
      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            key="body"
            initial={{ height: 0 }}
            animate={{ height: "auto" }}
            exit={{ height: 0 }}
            transition={{ duration: 0.28, ease: "easeOut" }}
            onUpdate={handleBodyUpdate}
            onAnimationComplete={resetHeightTracking}
            style={{ overflow: "hidden" }}
          >
            <div className="relative">
              <button
                type="button"
                onClick={toggle}
                aria-label="Свернуть прогон"
                className="group absolute left-[9px] top-0 bottom-0 flex w-[2px] items-center justify-center border-0 bg-transparent p-0 cursor-pointer"
              >
                <span className="block h-full w-[2px] rounded-full bg-border transition-colors group-hover:bg-foreground/50" />
              </button>
              <div className="ml-7 flex flex-col gap-2">
                {visibleAiMessages.map((m, index) => (
                  <Message
                    key={m.id}
                    message={m}
                    onWrite={maybeAutoScroll}
                    thread={thread}
                    resultsById={resultsById}
                    isLastAi={m.id === lastVisibleAiMessage?.id}
                    noContainer
                    hideActions
                    hideContent={hideFirstMessageContent && index === 0}
                  />
                ))}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <button
        type="button"
        onClick={toggle}
        className="flex w-full items-center gap-2 border-0 bg-transparent p-0 text-left text-sm cursor-pointer text-foreground/90 hover:text-foreground"
      >
        <span
          className="flex h-5 w-5 shrink-0 items-center justify-center text-muted-foreground transition-transform duration-200"
          style={{
            transform: expanded ? "rotate(-90deg)" : "rotate(0deg)",
          }}
          aria-hidden
        >
          <ChevronRight size={14} />
        </span>
        {inFlight && (
          <span className="flex h-5 w-5 shrink-0 items-center justify-center">
            <Loader size={14} className="animate-spin text-muted-foreground" />
          </span>
        )}
        <span className="min-w-0 flex-1 truncate">{headerLabel}</span>
      </button>
    </div>
  );
};

export default React.memo(AgentRun, (prev, next) => {
  return (
    prev.aiMessages === next.aiMessages &&
    prev.resultsById === next.resultsById &&
    prev.thread === next.thread &&
    prev.isLastInThread === next.isLastInThread
  );
});
