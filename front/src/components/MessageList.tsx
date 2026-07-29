import React, { useMemo, useRef } from "react";
import Message from "./Message.tsx";
import AgentRun from "./AgentRun.tsx";
import { Message as Message_ } from "@langchain/langgraph-sdk";
import { motion } from "framer-motion";
import WellcomeMessage from "./wellcome-message.tsx";
import ThinkingIndicator from "./ThinkingIndicator.tsx";
import type { UseStream } from "@langchain/langgraph-sdk/react";
import type { GraphState, PlanningSnapshot, PlanTodo } from "../interfaces.ts";
import ChatError from "./ChatError.tsx";
import { FOLLOW_UP_PROMPT_SUGGESTIONS_ENABLED } from "@/config";
import { useBranches } from "@/hooks/useBranches";
import { useFollowUpSuggestions } from "@/hooks/useThreadSuggestions";
import {
  getPromptSuggestionTitle,
  type PromptSuggestionScenario,
} from "@/types/prompt-suggestions";
import { getQuestionsResult } from "./questions/detect";
import LiveQuestionsForm from "./questions/LiveQuestionsForm";
import type { QuestionsResult } from "../interfaces.ts";
import { isResponseWidget } from "./widgets/registry";
import ResponseWidget, {
  type ResponseWidgetItem,
} from "./widgets/ResponseWidget";
import LivePlanApprovalCard from "./planning/LivePlanApprovalCard";
import TodoListWidget from "./planning/TodoListWidget";

const AnsweredQuestionsCard = React.lazy(
  () => import("./questions/AnsweredQuestionsCard.tsx"),
);

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
const PRESENT_PLAN_TOOL_NAME = "present_plan";
const WRITE_TODO_TOOL_NAME = "write_todo";

const hasVisibleToolCalls = (
  m: Message_,
  resultsById: Record<string, Message_>,
): boolean => {
  if (m.type !== "ai") return false;
  const tc = ((m as any).tool_calls ?? []) as Array<{
    name: string;
    id?: string;
  }>;
  // think, response-widget-результаты (genui-виджеты, MCP-аппы, карточки
  // планировщика) и ask_questions рендерятся ВНЕ рана, поэтому не считаются
  // видимыми тулами — шаг из одних только них не должен образовывать
  // схлопывающийся agent-ран (иначе получим пустой ран-бокс).
  return tc.some(
    (c) =>
      c.name !== THINK_TOOL_NAME &&
      c.name !== ASK_QUESTIONS_TOOL_NAME &&
      c.name !== PRESENT_PLAN_TOOL_NAME &&
      c.name !== WRITE_TODO_TOOL_NAME &&
      !isResponseWidget(c.id ? resultsById[c.id] : undefined),
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

// Результаты тулов, помеченные как response_widget (genui-виджеты, MCP-аппы,
// карточки планировщика — см. registry.isResponseWidget). Рендерятся ВНЕ
// схлопывающегося рана: самостоятельным блоком после рана либо под контентом
// сообщения (если шаг состоит только из них). Порядок сохраняется; ЧТО рисовать
// для каждого — решает диспетчер ResponseWidget.
const collectResponseWidgets = (
  aiMessages: Message_[],
  resultsById: Record<string, Message_>,
): ResponseWidgetItem[] => {
  const out: ResponseWidgetItem[] = [];
  for (const m of aiMessages) {
    for (const c of ((m as any).tool_calls ?? []) as Array<any>) {
      const result = c.id ? resultsById[c.id] : undefined;
      if (isResponseWidget(result)) out.push({ toolCall: c, result });
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
  // Standalone block emitted when ask_questions / a response-widget tool is
  // called in parallel with a visible tool: the visible tool stays in the run,
  // the card/widget renders right after it as its own block (see items grouping).
  | { kind: "questions"; cards: QuestionsCardItem[]; key: string }
  | { kind: "response"; items: ResponseWidgetItem[]; key: string }
  | { kind: "todo"; toolCallId?: string; key: string };

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

  const latestWriteTodoCall = useMemo(() => {
    for (
      let messageIndex = messages.length - 1;
      messageIndex >= 0;
      messageIndex--
    ) {
      const message = messages[messageIndex];
      if (message.type !== "ai") continue;
      const calls = ((message as any).tool_calls ?? []) as Array<{
        id?: string;
        name?: string;
      }>;
      for (let callIndex = calls.length - 1; callIndex >= 0; callIndex--) {
        if (calls[callIndex].name === WRITE_TODO_TOOL_NAME) {
          return {
            messageId: message.id,
            toolCallId: calls[callIndex].id,
          };
        }
      }
    }
    return null;
  }, [messages]);

  const latestTodoSnapshot = useMemo<PlanTodo[] | undefined>(() => {
    for (let index = messages.length - 1; index >= 0; index--) {
      const planning = (messages[index].additional_kwargs as any)?.planning as
        | PlanningSnapshot
        | undefined;
      if (planning?.type === "todo_snapshot") return planning.todos;
    }
    return undefined;
  }, [messages]);

  const items: RenderItem[] = useMemo(() => {
    const out: RenderItem[] = [];
    let buffer: Message_[] = [];
    let bufferHasVisibleToolCalls = false;
    let bufferHasLatestTodo = false;
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
        if (bufferHasLatestTodo && latestWriteTodoCall) {
          out.push({
            kind: "todo",
            toolCallId: latestWriteTodoCall.toolCallId,
            key: `todo-${latestWriteTodoCall.toolCallId ?? latestWriteTodoCall.messageId}`,
          });
        }
        buffer = [];
        bufferHasVisibleToolCalls = false;
        bufferHasLatestTodo = false;
      }
    };
    for (const m of renderable) {
      if (hasToolCalls(m)) {
        // ask_questions и response-widget-результаты прерывают ран.
        const questionCards = collectAnsweredQuestions([m], resultsById);
        const responseWidgets = collectResponseWidgets([m], resultsById);
        const hasCard = questionCards.length > 0 || responseWidgets.length > 0;
        const hasVisible = hasVisibleToolCalls(m, resultsById);
        const hasLatestTodo =
          !!latestWriteTodoCall && m.id === latestWriteTodoCall.messageId;

        // Pure card step (no other visible tool): render the message standalone
        // with its card/widget under its reasoning/content (attached via the
        // leading maps below) — [run] [questions/widget] [run].
        if (hasCard && !hasVisible) {
          flush();
          out.push({ kind: "single", message: m });
          if (hasLatestTodo) {
            out.push({
              kind: "todo",
              toolCallId: latestWriteTodoCall.toolCallId,
              key: `todo-${latestWriteTodoCall.toolCallId ?? latestWriteTodoCall.messageId}`,
            });
          }
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
        bufferHasLatestTodo = bufferHasLatestTodo || hasLatestTodo;

        // Parallel call: the visible tool stays in the run; close the run right
        // after this message and emit the card(s)/widget(s) as their own block —
        // [run …m(tool)] [questions/widget] [run].
        if (hasCard) {
          flush();
          const idKey = m.id ?? out.length;
          if (responseWidgets.length) {
            out.push({
              kind: "response",
              items: responseWidgets,
              key: `w-${idKey}`,
            });
          }
          if (questionCards.length) {
            out.push({
              kind: "questions",
              cards: questionCards,
              key: `q-${idKey}`,
            });
          }
        }
      } else {
        flush();
        out.push({ kind: "single", message: m });
      }
    }
    flush();
    return out;
  }, [latestWriteTodoCall, renderable, resultsById]);

  // Response-widget-результаты рендерятся под контентом того AI-сообщения,
  // которое их породило (pure-card "single" — оно прерывает ран, см. группировку
  // выше). Рисуются диспетчером ResponseWidget.
  const leadingResponseWidgetsByAiId = useMemo(() => {
    const map = new Map<string, ResponseWidgetItem[]>();
    for (let i = 0; i < items.length; i++) {
      const it = items[i];
      if (it.kind !== "single" || it.message.type !== "ai" || !it.message.id) {
        continue;
      }
      const widgets = collectResponseWidgets([it.message], resultsById);
      if (widgets.length) map.set(it.message.id, widgets);
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

  // id последнего AI-сообщения КАЖДОГО хода (перед следующим human или в конце
  // треда). В экспериментальном режиме только на них показывается кнопка экспорта
  // (см. Message.tsx): [Human][AI][Tool][AI✓][Human][AI][AI✓].
  const turnFinalAiIds = useMemo(() => {
    const ids = new Set<string>();
    let lastAi: string | null | undefined = null;
    for (const m of renderable) {
      if (m.type === "ai") lastAi = m.id;
      else if (m.type === "human") {
        if (lastAi) ids.add(lastAi);
        lastAi = null;
      }
    }
    if (lastAi) ids.add(lastAi);
    return ids;
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
        if (item.kind === "response") {
          return (
            <div
              key={item.key}
              className="px-[20px] mb-[20px] flex flex-col gap-2"
            >
              {item.items.map((w, i) => (
                <ResponseWidget
                  key={w.toolCall.id ?? `${item.key}-${i}`}
                  item={w}
                  thread={thread}
                  isStreaming={!!thread?.isLoading}
                />
              ))}
            </div>
          );
        }
        if (item.kind === "todo") {
          const result = item.toolCallId
            ? resultsById[item.toolCallId]
            : undefined;
          const planning = (result?.additional_kwargs as any)?.planning as
            | PlanningSnapshot
            | undefined;
          const todos =
            planning?.type === "todo_snapshot"
              ? planning.todos
              : branches.isViewingNonHead
                ? latestTodoSnapshot
                : (thread?.values?.todos ?? latestTodoSnapshot);
          return todos?.length ? (
            <div key={item.key} className="px-[20px] mb-[20px]">
              <TodoListWidget todos={todos} active={!!thread?.isLoading} />
            </div>
          ) : null;
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
            isTurnFinalAi={
              item.message.id ? turnFinalAiIds.has(item.message.id) : false
            }
            hideToolCalls={item.hideToolCalls}
            leadingResponseWidgets={
              item.message.id
                ? leadingResponseWidgetsByAiId.get(item.message.id)
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
      <LivePlanApprovalCard
        key={`plan-approval-${lastAiId ?? "none"}`}
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
      <ThinkingIndicator
        messages={messages}
        thread={thread}
        threadId={activeThreadId}
      />
    </div>
  );
};

export default MessageList;
