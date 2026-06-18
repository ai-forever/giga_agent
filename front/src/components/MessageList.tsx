import React, { useMemo, useRef } from "react";
import Message from "./Message.tsx";
import AgentRun from "./AgentRun.tsx";
import { Message as Message_ } from "@langchain/langgraph-sdk";
import { Loader2 } from "lucide-react";
import WellcomeMessage from "./wellcome-message.tsx";
import ThinkingIndicator from "./ThinkingIndicator.tsx";
import type { UseStream } from "@langchain/langgraph-sdk/react";
import { GraphState } from "../interfaces.ts";
import ChatError from "./ChatError.tsx";
import { FOLLOW_UP_PROMPT_SUGGESTIONS_ENABLED } from "@/config";
import { useBranches } from "@/hooks/useBranches";
import { useFollowUpSuggestions } from "@/hooks/useThreadSuggestions";
import {
  getPromptSuggestionTitle,
  type PromptSuggestionScenario,
} from "@/types/prompt-suggestions";

interface MessageListProps {
  messages: Message_[];
  thread?: UseStream<GraphState>;
  threadId?: string;
  children?: React.ReactNode;
  notShowWelcomeMessage?: boolean;
  maybeAutoScroll: () => void;
  onSelectSuggestion?: (suggestion: PromptSuggestionScenario) => void;
}

const THINK_TOOL_NAME = "think";

const hasVisibleToolCalls = (m: Message_): boolean => {
  if (m.type !== "ai") return false;
  const tc = ((m as any).tool_calls ?? []) as Array<{ name: string }>;
  return tc.some((c) => c.name !== THINK_TOOL_NAME);
};

const hasToolCalls = (m: Message_): boolean => {
  if (m.type !== "ai") return false;
  return ((m as any).tool_calls ?? []).length > 0;
};

const getMessageText = (message: Message_): string => {
  if (Array.isArray(message.content)) {
    return message.content
      .filter((part: any) => part.type === "text")
      .map((part: any) => part.text)
      .join("\n\n");
  }
  return (message.content as string) ?? "";
};

const stripThinkingTags = (text: string): string =>
  text
    .replace(/<thinking>[\s\S]*?<\/thinking>\s*/g, "")
    .replace(/<thinking>[\s\S]*$/g, "")
    .trim();

const hasContentOutsideThinking = (m: Message_): boolean =>
  m.type === "ai" && stripThinkingTags(getMessageText(m)).length > 0;

type RenderItem =
  | { kind: "single"; message: Message_; hideToolCalls?: boolean }
  | { kind: "run"; aiMessages: Message_[]; key: string };

const MessageList: React.FC<MessageListProps> = ({
  messages: messagesProp,
  thread,
  threadId: routeThreadId,
  children,
  notShowWelcomeMessage,
  maybeAutoScroll,
  onSelectSuggestion,
}) => {
  const branches = useBranches();
  // When viewing a non-head branch, render that branch's messages instead of
  // the live head. During streaming we stay on the head (activeBranch is "").
  const messages = branches.isViewingNonHead
    ? branches.activeMessages
    : messagesProp;
  const resultsById = useMemo(() => {
    const map: Record<string, Message_> = {};
    for (const m of messages) {
      if (m.type === "tool") {
        const id = (m as any).tool_call_id;
        if (id) map[id] = m;
      }
    }
    return map;
  }, [messages]);

  const renderable = useMemo(
    () =>
      messages.filter(
        (message) =>
          message.type !== "tool" &&
          (message.additional_kwargs?.tool_name as string) !== "think",
      ),
    [messages],
  );

  const items: RenderItem[] = useMemo(() => {
    const out: RenderItem[] = [];
    let buffer: Message_[] = [];
    let bufferHasVisibleToolCalls = false;
    const flush = () => {
      if (buffer.length) {
        if (bufferHasVisibleToolCalls) {
          out.push({
            kind: "run",
            aiMessages: buffer,
            key: `run-${buffer[0].id ?? out.length}`,
          });
        } else {
          for (const message of buffer) {
            out.push({ kind: "single", message });
          }
        }
        buffer = [];
        bufferHasVisibleToolCalls = false;
      }
    };
    for (const m of renderable) {
      if (hasToolCalls(m)) {
        if (buffer.length && hasContentOutsideThinking(m)) {
          flush();
          out.push({
            kind: "single",
            message: m,
            hideToolCalls: true,
          });
        }
        buffer.push(m);
        bufferHasVisibleToolCalls =
          bufferHasVisibleToolCalls || hasVisibleToolCalls(m);
      } else {
        flush();
        out.push({ kind: "single", message: m });
      }
    }
    flush();
    return out;
  }, [renderable]);

  const lastAiId = useMemo(() => {
    for (let i = renderable.length - 1; i >= 0; i--) {
      if (renderable[i].type === "ai") return renderable[i].id;
    }
    return null;
  }, [renderable]);
  const activeThreadId =
    routeThreadId ??
    ((thread as any)?.threadId as string | undefined) ??
    undefined;
  const canShowFollowUps =
    FOLLOW_UP_PROMPT_SUGGESTIONS_ENABLED &&
    Boolean(activeThreadId) &&
    Boolean(lastAiId) &&
    !thread?.isLoading &&
    !branches.isViewingNonHead;
  const { suggestions: followUpSuggestions, isLoading: isFollowUpsLoading } =
    useFollowUpSuggestions({
      threadId: activeThreadId,
      messages: renderable,
      enabled: canShowFollowUps,
    });

  // "Историческими" считаются все руны, которые УЖЕ есть в треде до того, как
  // пользователь впервые что-то отправил (т.е. до того, как мы увидели
  // thread.isLoading=true). Пока сессия не «началась», переписываем снимок
  // на каждом рендере — это закрывает гонку, когда messages приходят в
  // несколько этапов (на первом рендере run может ещё отсутствовать в items,
  // на следующем — появиться).
  // Дополнительно сбрасываем оба состояния при смене treadId, иначе ref
  // переживёт навигацию между тредами и заблокирует фикс для нового.
  const historicalRunKeysRef = useRef<Set<string>>(new Set());
  const sessionStartedRef = useRef<boolean>(false);
  const lastThreadIdRef = useRef<string | null | undefined>(undefined);
  const streamThreadId = (thread as any)?.threadId as string | null | undefined;

  if (lastThreadIdRef.current !== streamThreadId) {
    lastThreadIdRef.current = streamThreadId;
    historicalRunKeysRef.current = new Set();
    sessionStartedRef.current = false;
  }

  if (thread?.isLoading) sessionStartedRef.current = true;

  if (!sessionStartedRef.current) {
    historicalRunKeysRef.current = new Set(
      items.filter((i) => i.kind === "run").map((i) => (i as any).key),
    );
  }

  return (
    <div
      className="flex-1 p-5 max-[900px]:p-0"
      style={{ overflowAnchor: "none" }}
    >
      {children}
      {messages.length === 0 && !notShowWelcomeMessage ? (
        <WellcomeMessage />
      ) : null}
      {items.map((item, idx) => {
        if (item.kind === "run") {
          const appearedInSession = !historicalRunKeysRef.current.has(item.key);
          const previousItem = items[idx - 1];
          const nextItem = items[idx + 1];
          const hasHumanAfter = items
            .slice(idx + 1)
            .some(
              (next) => next.kind === "single" && next.message.type === "human",
            );
          const hasRunAfter = items
            .slice(idx + 1)
            .some((next) => next.kind === "run");
          const durationStartMessage =
            previousItem?.kind === "single" &&
            (previousItem.message.type === "human" ||
              previousItem.message.type === "ai")
              ? previousItem.message
              : undefined;
          const durationEndMessage =
            nextItem?.kind === "single" && nextItem.message.type === "ai"
              ? nextItem.message
              : undefined;
          const hideFirstMessageContent =
            previousItem?.kind === "single" &&
            previousItem.hideToolCalls &&
            previousItem.message.id === item.aiMessages[0]?.id;
          return (
            <AgentRun
              key={item.key}
              aiMessages={item.aiMessages}
              resultsById={resultsById}
              thread={thread}
              isLastInThread={!hasHumanAfter && !hasRunAfter}
              maybeAutoScroll={maybeAutoScroll}
              durationStartMessage={durationStartMessage}
              durationEndMessage={durationEndMessage}
              hideFirstMessageContent={hideFirstMessageContent}
              appearedInSession={appearedInSession}
            />
          );
        }
        return (
          <Message
            key={item.message.id ?? idx}
            message={item.message}
            onWrite={maybeAutoScroll}
            thread={thread}
            resultsById={resultsById}
            isLastAi={item.message.id === lastAiId}
            hideToolCalls={item.hideToolCalls}
          />
        );
      })}
      {canShowFollowUps && (
        <div className="px-[34px] py-2">
          {isFollowUpsLoading ? (
            <div className="inline-flex items-center gap-2 text-sm text-muted-foreground animate-pulse">
              <Loader2 className="size-4 animate-spin" />
              Генерируем подсказки...
            </div>
          ) : followUpSuggestions.length > 0 ? (
            <div className="flex flex-wrap items-center gap-2">
              {followUpSuggestions.map((item, idx) => (
                <button
                  key={`${item.text}-${idx}`}
                  type="button"
                  onClick={() => onSelectSuggestion?.(item)}
                  className="rounded-full border border-border bg-muted/40 px-3 py-1.5 text-xs text-foreground/90 transition-colors hover:bg-muted cursor-pointer"
                >
                  {getPromptSuggestionTitle(item)}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      )}
      <ChatError thread={thread} />
      <ThinkingIndicator messages={messages} thread={thread} />
    </div>
  );
};

export default MessageList;
