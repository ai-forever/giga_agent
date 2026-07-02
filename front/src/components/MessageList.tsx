import React, { useMemo, useRef } from "react";
import Message from "./Message.tsx";
import AgentRun from "./AgentRun.tsx";
import { Message as Message_ } from "@langchain/langgraph-sdk";
import { motion } from "framer-motion";
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
import { getScheduledTaskId } from "./scheduler/detect";
import { getQuestionsResult } from "./questions/detect";
import LiveQuestionsForm from "./questions/LiveQuestionsForm";
import type { QuestionsResult } from "../interfaces.ts";

const AnsweredQuestionsCard = React.lazy(
  () => import("./questions/AnsweredQuestionsCard.tsx"),
);
const SchedulerTaskChatCard = React.lazy(
  () => import("./scheduler/chat-card.tsx"),
);
const McpUiWidget = React.lazy(() => import("./attachments/McpUiWidget.tsx"));

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
const ASK_QUESTIONS_TOOL_NAME = "ask_questions";

const hasVisibleToolCalls = (
  m: Message_,
  resultsById: Record<string, Message_>,
): boolean => {
  if (m.type !== "ai") return false;
  const tc = ((m as any).tool_calls ?? []) as Array<{
    name: string;
    id?: string;
  }>;
  // think, promoted schedule_task cards and ask_questions (its live form and
  // answered card render outside the run) don't count as visible tool calls —
  // a step consisting only of those should not form a collapsible agent run.
  return tc.some(
    (c) =>
      c.name !== THINK_TOOL_NAME &&
      c.name !== ASK_QUESTIONS_TOOL_NAME &&
      !getScheduledTaskId(c.id ? resultsById[c.id] : undefined),
  );
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

// Interactive MCP-app widgets produced by a run's tool calls. They render at the
// top of the AI message that follows the run (not inside the collapsible run).
const collectMcpUiWidgets = (
  aiMessages: Message_[],
  resultsById: Record<string, Message_>,
): any[] => {
  const out: any[] = [];
  for (const m of aiMessages) {
    for (const c of ((m as any).tool_calls ?? []) as Array<{ id?: string }>) {
      const result = c.id ? resultsById[c.id] : undefined;
      const atts = (result?.additional_kwargs?.tool_attachments as any[]) ?? [];
      for (const a of atts) {
        if (a?.file_type === "mcp_ui" && a?.resource_uri) out.push(a);
      }
    }
  }
  return out;
};

// Scheduled-task cards produced by a run's tool calls. Like MCP widgets, they
// render as a standalone block on the AI message that follows the run, not
// inside the collapsible tool-call list.
const collectScheduledTasks = (
  aiMessages: Message_[],
  resultsById: Record<string, Message_>,
): string[] => {
  const out: string[] = [];
  for (const m of aiMessages) {
    for (const c of ((m as any).tool_calls ?? []) as Array<{ id?: string }>) {
      const result = c.id ? resultsById[c.id] : undefined;
      const taskId = getScheduledTaskId(result);
      if (taskId) out.push(taskId);
    }
  }
  return out;
};

// Completed `ask_questions` calls render as a standalone read-only card (the
// questions asked + how the user answered them), like scheduled-task cards.
export interface QuestionsCardItem {
  id: string;
  data: QuestionsResult;
}

const collectAnsweredQuestions = (
  aiMessages: Message_[],
  resultsById: Record<string, Message_>,
): QuestionsCardItem[] => {
  const out: QuestionsCardItem[] = [];
  for (const m of aiMessages) {
    for (const c of ((m as any).tool_calls ?? []) as Array<{ id?: string }>) {
      const result = c.id ? resultsById[c.id] : undefined;
      const data = getQuestionsResult(result);
      if (data && c.id) out.push({ id: c.id, data });
    }
  }
  return out;
};

type RenderItem =
  | { kind: "single"; message: Message_; hideToolCalls?: boolean }
  | { kind: "run"; aiMessages: Message_[]; key: string }
  // Standalone card emitted when ask_questions/schedule_task is called in
  // parallel with a visible tool: the visible tool stays in the run, the card
  // renders right after it as its own block (see items grouping).
  | { kind: "questions"; cards: QuestionsCardItem[]; key: string }
  | { kind: "scheduled"; taskIds: string[]; key: string }
  | { kind: "widgets"; widgets: any[]; key: string };

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
        // ask_questions / schedule_task / MCP-app widgets interrupt the run.
        const questionCards = collectAnsweredQuestions([m], resultsById);
        const taskIds = collectScheduledTasks([m], resultsById);
        const widgets = collectMcpUiWidgets([m], resultsById);
        const hasCard =
          questionCards.length > 0 || taskIds.length > 0 || widgets.length > 0;
        const hasVisible = hasVisibleToolCalls(m, resultsById);

        // Pure card step (no other visible tool): render the message standalone
        // with its card under its reasoning/content (card attached via the
        // leading maps below) — [run] [questions/scheduler] [run].
        if (hasCard && !hasVisible) {
          flush();
          out.push({ kind: "single", message: m });
          continue;
        }

        if (buffer.length && hasContentOutsideThinking(m)) {
          flush();
          out.push({
            kind: "single",
            message: m,
            hideToolCalls: true,
          });
        }
        buffer.push(m);
        bufferHasVisibleToolCalls = bufferHasVisibleToolCalls || hasVisible;

        // Parallel call: the visible tool stays in the run; close the run right
        // after this message and emit the card(s) as their own block —
        // [run …m(tool)] [questions/scheduler/widget] [run].
        if (hasCard) {
          flush();
          const idKey = m.id ?? out.length;
          if (taskIds.length) {
            out.push({ kind: "scheduled", taskIds, key: `sched-${idKey}` });
          }
          if (questionCards.length) {
            out.push({ kind: "questions", cards: questionCards, key: `q-${idKey}` });
          }
          if (widgets.length) {
            out.push({ kind: "widgets", widgets, key: `w-${idKey}` });
          }
        }
      } else {
        flush();
        out.push({ kind: "single", message: m });
      }
    }
    flush();
    return out;
  }, [renderable, resultsById]);

  // Scheduled-task cards render as a standalone block on the AI message that
  // issued schedule_task — that message is always a split-point "single" (it
  // interrupts the run, see items grouping above).
  const leadingScheduledTasksByAiId = useMemo(() => {
    const map = new Map<string, string[]>();
    for (let i = 0; i < items.length; i++) {
      const it = items[i];
      if (it.kind !== "single" || it.message.type !== "ai" || !it.message.id) {
        continue;
      }
      const taskIds = collectScheduledTasks([it.message], resultsById);
      if (taskIds.length) map.set(it.message.id, taskIds);
    }
    return map;
  }, [items, resultsById]);

  // Answered-questions cards render on the AI message that issued ask_questions —
  // that message is always a split-point "single" (it interrupts the run, see
  // items grouping above). The card renders under its reasoning/content (see
  // Message.tsx).
  const answeredQuestionsByAiId = useMemo(() => {
    const map = new Map<string, QuestionsCardItem[]>();
    for (let i = 0; i < items.length; i++) {
      const it = items[i];
      if (it.kind !== "single" || it.message.type !== "ai" || !it.message.id) {
        continue;
      }
      const cards = collectAnsweredQuestions([it.message], resultsById);
      if (cards.length) map.set(it.message.id, cards);
    }
    return map;
  }, [items, resultsById]);

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

  // Плавное появление (blur→clear) подсказок при генерации. Решение об
  // анимации вычисляем синхронно в рендере (через ref), чтобы оно было готово
  // на момент маунта motion-блока и не зависело от порядка эффектов.
  const followUpsLoadStartRef = useRef<number | null>(null);
  const followUpsResolvedRef = useRef<boolean>(false);
  const followUpsAnimateRef = useRef<boolean>(false);

  if (lastThreadIdRef.current !== streamThreadId) {
    lastThreadIdRef.current = streamThreadId;
    historicalRunKeysRef.current = new Set();
    sessionStartedRef.current = false;
    followUpsLoadStartRef.current = null;
    followUpsResolvedRef.current = false;
    followUpsAnimateRef.current = false;
  }

  if (thread?.isLoading) sessionStartedRef.current = true;

  if (!sessionStartedRef.current) {
    historicalRunKeysRef.current = new Set(
      items.filter((i) => i.kind === "run").map((i) => (i as any).key),
    );
  }

  // Засекаем старт генерации; когда подсказки приехали — решаем, анимировать
  // ли. Анимацию пропускаем, если это первая загрузка страницы (сессия ещё не
  // началась) и подсказки приехали быстрее 2с — тогда они появляются вместе со
  // страницей и не должны перетягивать внимание.
  if (isFollowUpsLoading) {
    followUpsResolvedRef.current = false;
    if (followUpsLoadStartRef.current === null) {
      followUpsLoadStartRef.current = Date.now();
    }
  } else if (followUpSuggestions.length > 0 && !followUpsResolvedRef.current) {
    followUpsResolvedRef.current = true;
    const start = followUpsLoadStartRef.current;
    const elapsed = start != null ? Date.now() - start : 0;
    const isFirstLoadFast = !sessionStartedRef.current && elapsed < 2000;
    followUpsAnimateRef.current = !isFirstLoadFast;
    followUpsLoadStartRef.current = null;
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
        if (item.kind === "questions") {
          return (
            <div
              key={item.key}
              className="px-[20px] mb-[20px] flex flex-col gap-2"
            >
              {item.cards.map((c) => (
                <React.Suspense key={c.id} fallback={null}>
                  <AnsweredQuestionsCard data={c.data} />
                </React.Suspense>
              ))}
            </div>
          );
        }
        if (item.kind === "scheduled") {
          return (
            <div
              key={item.key}
              className="px-[20px] mb-[20px] flex flex-col gap-2"
            >
              {item.taskIds.map((id) => (
                <React.Suspense key={id} fallback={null}>
                  <SchedulerTaskChatCard taskId={id} />
                </React.Suspense>
              ))}
            </div>
          );
        }
        if (item.kind === "widgets") {
          return (
            <div
              key={item.key}
              className="px-[20px] mb-[20px] flex flex-col gap-2"
            >
              {item.widgets.map((att, i) => (
                <React.Suspense
                  key={`${att.resource_uri ?? "w"}-${i}`}
                  fallback={
                    <div className="text-xs text-muted-foreground">
                      Загрузка виджета…
                    </div>
                  }
                >
                  <McpUiWidget
                    serverRef={att.server_id ?? att.server}
                    resourceUri={att.resource_uri}
                    toolName={att.tool}
                    appName={att.server}
                    iconUrl={att.icon}
                    toolArgs={att.tool_args}
                    structuredContent={att.structured_content}
                  />
                </React.Suspense>
              ))}
            </div>
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
            isLast={idx === items.length - 1}
            hideToolCalls={item.hideToolCalls}
            leadingScheduledTasks={
              item.message.id
                ? leadingScheduledTasksByAiId.get(item.message.id)
                : undefined
            }
            answeredQuestions={
              item.message.id
                ? answeredQuestionsByAiId.get(item.message.id)
                : undefined
            }
          />
        );
      })}
      <LiveQuestionsForm
        key={`questions-${lastAiId ?? "none"}`}
        thread={thread}
      />
      {canShowFollowUps && followUpSuggestions.length > 0 && (
        <div className="px-[20px]">
          <motion.div
            className="flex flex-wrap items-center gap-2"
            initial={
              followUpsAnimateRef.current
                ? { opacity: 0, filter: "blur(8px)" }
                : false
            }
            animate={{ opacity: 1, filter: "blur(0px)" }}
            transition={{ duration: 0.5, ease: "easeOut" }}
          >
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
          </motion.div>
        </div>
      )}
      <ChatError thread={thread} />
      <ThinkingIndicator messages={messages} thread={thread} />
    </div>
  );
};

export default MessageList;
