import React, {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Checkpoint, Message as Message_ } from "@langchain/langgraph-sdk";
import MessageAttachments from "./MessageAttachments.tsx";
import type { UseStream } from "@langchain/langgraph-sdk/react";
import { GraphState, GraphTemplate } from "../interfaces.ts";
import MessageEditor from "./MessageEditor.tsx";
import ToolCallsList from "./ToolCallsList.tsx";
import { findScrollRoot } from "@/lib/scroll";
import { useBranches } from "@/hooks/useBranches";
import { Check, Download, Pencil, RefreshCw, X } from "lucide-react";
import { BranchSwitcher } from "./BranchSwitcher.tsx";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  exportChat,
  type ExportFormat,
  extractMessagePair,
} from "@/lib/chat-export";
import { toast } from "sonner";
import { useSelectedAttachments } from "../hooks/SelectedAttachmentsContext.tsx";
import TextMarkdown from "./attachments/TextMarkdown.tsx";
import { AnimatePresence, motion } from "framer-motion";
import { useUserInfo } from "@/components/providers/user-info-context.ts";
import { BROWSER_USE_NAME } from "@/config.ts";
import { useSettings } from "./Settings.tsx";
import type { QuestionsCardItem } from "./MessageList.tsx";
import { isResponseWidget } from "./widgets/registry";
import ResponseWidget, {
  type ResponseWidgetItem,
} from "./widgets/ResponseWidget";

const AnsweredQuestionsCard = React.lazy(
  () => import("./questions/AnsweredQuestionsCard.tsx"),
);

function getMessageText(message: Message_): string {
  if (Array.isArray(message.content)) {
    return message.content
      .filter((p: any) => p.type === "text")
      .map((p: any) => p.text)
      .join("\n\n");
  }
  return (message.content as string) ?? "";
}

const EXPORT_TITLE_MAX_LEN = 60;

function getHumanMessageText(message: Message_): string {
  const rawText =
    (message.additional_kwargs as Record<string, string>)?.user_input ??
    getMessageText(message);
  return rawText.replace(/\n*\[system:[\s\S]*$/i, "").trimEnd();
}

interface MessageProps {
  message: Message_;
  onWrite: () => void;
  onWriteEnd?: () => void;
  writeMessage?: boolean;
  thread?: UseStream<GraphState, GraphTemplate>;
  resultsById?: Record<string, Message_>;
  isLastAi?: boolean;
  // Последнее сообщение в треде — у него убираем нижний отступ.
  isLast?: boolean;
  // Когда true — рендер AI-с-tool_calls без своей рамки/фона/паддингов
  // (используется внутри AgentRun, чтобы избежать вложенных карточек).
  noContainer?: boolean;
  // Скрывает нижний ряд action-кнопок (refresh/download/branch/edit) —
  // нужно для шагов внутри AgentRun, кнопки остаются только у финального AI.
  hideActions?: boolean;
  // Показывает только reasoning/content AI-сообщения, не рендеря tool calls.
  hideToolCalls?: boolean;
  // Показывает только tool calls, не дублируя уже вынесенный content/reasoning.
  hideContent?: boolean;
  // Вынесенные наружу виджеты/карточки (genui, MCP-аппы, планировщик) — если
  // шаг состоял только из них, рендерятся отдельным блоком ПОД reasoning/content
  // этого AI-сообщения через диспетчер ResponseWidget (см. MessageList).
  leadingResponseWidgets?: ResponseWidgetItem[];
  // Карточки уже отвеченных уточняющих вопросов (тул ask_questions) —
  // рендерятся отдельным блоком ПОД reasoning/content этого AI-сообщения
  // (см. MessageList).
  answeredQuestions?: QuestionsCardItem[];
}

// ≈ 10 строк text-xs (12px) при leading-snug (line-height 1.375): 12 * 1.375 * 10 ≈ 165
const REASONING_CLAMP_PX = 165;
const REASONING_OVERFLOW_TOLERANCE_PX = 4;

const FADE_MASK =
  "linear-gradient(to bottom, black 0%, black 35%, transparent 100%)";

const ReasoningContent: React.FC<{
  text: string;
  contentRef: React.RefObject<HTMLDivElement | null>;
}> = ({ text, contentRef }) => (
  <div ref={contentRef} className="leading-snug">
    {text.split("\n").map((line, index) =>
      line.trim() ? (
        <span key={index} className="block">
          {line}
        </span>
      ) : (
        <span key={index} className="block h-[5px]" aria-hidden />
      ),
    )}
  </div>
);

const ReasoningBlock: React.FC<{ text: string }> = ({ text }) => {
  const [expanded, setExpanded] = useState(false);
  const [isOverflowing, setIsOverflowing] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const lastHeightRef = useRef<number | null>(null);

  useLayoutEffect(() => {
    if (!contentRef.current) return;
    const h = contentRef.current.offsetHeight;
    setIsOverflowing(h > REASONING_CLAMP_PX + REASONING_OVERFLOW_TOLERANCE_PX);
  }, [text]);

  if (!text?.trim()) return null;

  // Содержимое влезает в 3 строки — рендерим без motion/маски/клика.
  if (!isOverflowing) {
    return (
      <div className="text-xs italic text-muted-foreground">
        <ReasoningContent text={text} contentRef={contentRef} />
      </div>
    );
  }

  const clamped = !expanded;

  const handleUpdate = (latest: { height?: number | string }) => {
    if (typeof latest.height !== "number") return;
    const prev = lastHeightRef.current;
    if (prev != null) {
      const delta = latest.height - prev;
      if (Math.abs(delta) > 0.25) {
        const root = findScrollRoot(containerRef.current);
        if (root) root.scrollTop += delta;
      }
    }
    lastHeightRef.current = latest.height;
  };

  return (
    <motion.div
      ref={containerRef}
      onClick={() => setExpanded((v) => !v)}
      initial={false}
      animate={{ height: clamped ? REASONING_CLAMP_PX : "auto" }}
      transition={{ duration: 0.28, ease: "easeOut" }}
      onUpdate={handleUpdate}
      onAnimationStart={() => {
        lastHeightRef.current = containerRef.current?.offsetHeight ?? null;
      }}
      onAnimationComplete={() => {
        lastHeightRef.current = null;
      }}
      className="relative mb-2 text-xs italic text-muted-foreground cursor-pointer select-none"
      style={{
        overflow: "hidden",
        WebkitMaskImage: clamped ? FADE_MASK : "none",
        maskImage: clamped ? FADE_MASK : "none",
      }}
    >
      <ReasoningContent text={text} contentRef={contentRef} />
    </motion.div>
  );
};

const THINK_TOOL_NAME = "think";

interface RenderToolCall {
  name: string;
  args: Record<string, any>;
}

const getThinkText = (toolCall: RenderToolCall): string => {
  const args = toolCall?.args;
  if (!args || typeof args !== "object") {
    return "";
  }

  if (typeof args.thought === "string" && args.thought.trim()) {
    return args.thought;
  }

  if (typeof args.thoughts === "string" && args.thoughts.trim()) {
    return args.thoughts;
  }

  return "";
};

const normalizeReasoningText = (text: string): string =>
  text
    .split("\n")
    .map((line) => line.trimEnd())
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();

const Message: React.FC<MessageProps> = ({
  message,
  onWrite,
  onWriteEnd,
  thread,
  writeMessage = false,
  resultsById,
  isLastAi = false,
  // @ts-ignore
  isLast = false,
  noContainer = false,
  hideActions = false,
  hideToolCalls = false,
  hideContent = false,
  leadingResponseWidgets,
  answeredQuestions,
}) => {
  // 2) хук для постепенной «печати» чанков
  const displayedRef = useRef<string>(""); // накапливаемый текст
  const [displayed, setDisplayed] = useState<string>("");
  const [edit, setEdit] = useState<boolean>(false);
  const [showEdit, setShowEdit] = useState<boolean>(false);
  const [isApprovalLoading, setIsApprovalLoading] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const { setSelectedAttachments, clear } = useSelectedAttachments();
  const { mcpTools } = useUserInfo();

  const handleExport = async (format: ExportFormat) => {
    if (!thread || isExporting) return;
    setIsExporting(true);
    const toastId = toast.loading("Экспорт сообщения...");
    try {
      const pair = extractMessagePair(thread.messages, message);
      const originHuman = pair.find((m) => m.type === "human");
      const title =
        (originHuman ? getHumanMessageText(originHuman as Message_) : "")
          .slice(0, EXPORT_TITLE_MAX_LEN)
          .replace(/\s+/g, " ")
          .trim() || "chat";
      await exportChat(pair, format, title);
      toast.success("Экспорт завершён", { id: toastId });
    } catch {
      toast.error("Не удалось выполнить экспорт", { id: toastId });
    } finally {
      setIsExporting(false);
    }
  };

  const idxRef = useRef<number>(0);

  useEffect(() => {
    const messageContent = Array.isArray(message.content)
      ? message.content
          .filter((part) => part.type === "text")
          .map((part) => part.text)
          .join("\n\n")
      : message.content;
    if (message.type === "human" && !writeMessage) {
      const rawText =
        (message.additional_kwargs as Record<string, string>)?.user_input ??
        messageContent ??
        "";
      const humanText = rawText.replace(/\n*\[system:[\s\S]*$/i, "").trimEnd();
      displayedRef.current = humanText;
      setDisplayed(humanText);
      return;
    }
    if (message.type !== "ai" && !writeMessage) {
      // если не ai — сразу пишем весь текст
      displayedRef.current = messageContent;
      setDisplayed(messageContent);
      return;
    }

    // @ts-ignore
    if (message.additional_kwargs["rendered"]) {
      displayedRef.current = messageContent;
      setDisplayed(messageContent);
      return;
    }

    const words = messageContent;
    let timer: NodeJS.Timeout;

    const step = () => {
      // случайный размер чанка: от 1 до 4 слов
      const chunkSize = Math.max(10, Math.floor(Math.random() * 20) + 1);
      const next = Math.min(idxRef.current + chunkSize, words.length);
      // добавляем words[idx..next]
      displayedRef.current =
        displayedRef.current + words.slice(idxRef.current, next);
      setDisplayed(displayedRef.current);
      idxRef.current = next;
      if (idxRef.current < words.length) {
        // случайная задержка: 20–120 мс
        const delay = 20 + Math.random() * 40;
        timer = setTimeout(step, delay);
      } else {
        onWriteEnd?.();
      }
    };

    step();

    return () => clearTimeout(timer);
    // @ts-ignore
  }, [message.content, message.additional_kwargs, message.type]);
  const rawHasToolCalls =
    message.type === "ai" &&
    Array.isArray((message as any).tool_calls) &&
    (message as any).tool_calls.length > 0;
  const hasToolCalls = !hideToolCalls && rawHasToolCalls;

  const { normalizedContent, inlineReasoning } = useMemo(() => {
    let md = displayed ?? "";

    // 1) перед каждым ``` вставляем гарантированно пустую строку
    md = md.replace(/(^|\n)(```[^\n]*)/g, "$1\n$2");

    // 2) Извлекаем все <thinking>...</thinking> блоки из текста сообщения
    // и склеиваем их в inlineReasoning — он попадёт в ReasoningBlock вместе
    // с reasoning_content и think-tool вызовами.
    const reasoningParts: string[] = [];
    md = md.replace(
      /<thinking>([\s\S]*?)<\/thinking>\s*/g,
      (_, content: string) => {
        const t = content.trim();
        if (t) reasoningParts.push(t);
        return "";
      },
    );

    // Незакрытый <thinking> (стриминг ещё не дошёл до </thinking>):
    // забираем хвост после открывающего тега как «текущее» рассуждение.
    const openIdx = md.indexOf("<thinking>");
    if (openIdx !== -1 && md.indexOf("</thinking>", openIdx) === -1) {
      const tail = md.slice(openIdx + "<thinking>".length).trim();
      if (tail) reasoningParts.push(tail);
      md = md.slice(0, openIdx);
    }

    return {
      normalizedContent: md.trim(),
      inlineReasoning: reasoningParts.join("\n\n").trim(),
    };
  }, [displayed]);

  useEffect(() => {
    onWrite();
  }, [normalizedContent, onWrite]);

  const branches = useBranches();
  const onRefresh = async () => {
    // Index against the branch currently being viewed (head by default).
    const messages = branches.isViewingNonHead
      ? branches.activeMessages
      : (thread?.messages ?? []);
    const targetIndex = messages.findIndex((m) => m.id === message.id);
    if (targetIndex < 0) return;
    const previousMessage = messages[targetIndex - 1];
    const parentMessage: Message_[] = [];
    // TODO: Сейчас это нужно, чтобы giga_agent адекватно работал с aegра, так как в их API нельзя просто передавать checkpoint (без input)
    const { meta, history } = await branches.resolveForkData(message);
    // Fork point = the checkpoint whose message list is exactly the prefix
    // before the regenerated message (ends at previousMessage), resolved
    // against the currently viewed branch. Fall back to the message's
    // first-seen parent checkpoint when no exact prefix match exists.
    const localMatchingState = previousMessage
      ? history.find((state) => {
          const stateMessages = state.values?.messages ?? [];
          return (
            stateMessages.length === targetIndex &&
            stateMessages.at(-1)?.id === previousMessage.id
          );
        })
      : undefined;
    const effectiveParentCheckpoint = (localMatchingState?.checkpoint ??
      meta?.firstSeenState?.parent_checkpoint) as Checkpoint | undefined;

    // Stream the regenerated run into the head view.
    branches.switchBranch("");
    thread?.submit(
      { messages: parentMessage },
      {
        checkpoint: effectiveParentCheckpoint
          ? ({ ...effectiveParentCheckpoint } as Checkpoint)
          : undefined,
        optimisticValues(prev: GraphState) {
          const prevMessages = prev.messages ?? [];
          const nextMessages = prevMessages.slice(0, targetIndex);
          return { ...prev, messages: nextMessages };
        },
        streamMode: ["messages"],
        onDisconnect: "continue",
      },
    );
  };

  const interruptType = thread?.interrupt?.value?.type;
  const isDestructiveConfirm = interruptType === "confirm_destructive";
  // Лейбл подтверждения по имени тула: деструктив — не только удаление
  // (mail_send — отправка). Берём из interrupt.value.tools.
  const destructiveLabel = (() => {
    const names = (
      (thread?.interrupt?.value?.tools ?? []) as { name?: string }[]
    )
      .map((t) => t?.name || "")
      .filter(Boolean);
    if (names.length === 1) {
      const n = names[0];
      if (n === "mail_send") return "отправку письма";
      if (n === "calendar_create_event") return "создание события";
      if (/_(delete|remove|drop|purge)$/.test(n) || n.includes("delete"))
        return "удаление";
    }
    return "действие";
  })();
  const isSystemNotice =
    message.type === "ai" &&
    // @ts-ignore — служебное сообщение от инфраструктуры (tool-router и т.п.)
    message.additional_kwargs?.kind === "system_notice";
  const isCurrentInterruptMessage =
    !hideToolCalls &&
    message.type === "ai" &&
    !!thread?.interrupt?.value &&
    ["approve", "tool_call"].includes(thread.interrupt.value.type) &&
    // @ts-ignore
    !!message.tool_calls?.length &&
    thread?.messages.at(-1)?.id === message.id;

  const handleInterruptAction = async (type: "comment" | "approve") => {
    if (!thread?.interrupt?.value || isApprovalLoading) return;
    const interruptType = thread.interrupt.value.type;

    if (
      type === "approve" &&
      interruptType === "tool_call" &&
      thread.interrupt.value.tools
    ) {
      const mcpToolMap = Object.fromEntries(
        mcpTools.map((tool) => [tool.name, tool]),
      );
      const toolCalls = thread.interrupt.value.tools;
      setIsApprovalLoading(true);
      const results = await Promise.all(
        toolCalls.map((call) =>
          mcpToolMap[call.name].callTool(call.args).catch((e) => e),
        ),
      );
      setIsApprovalLoading(false);

      thread.submit(undefined, {
        command: {
          resume: {
            type,
            results: results.map((result, index) => ({
              result,
              id: toolCalls[index].id,
            })),
          },
        },
        onDisconnect:
          // @ts-ignore
          thread?.messages.at(-1).tool_calls?.[0]?.name === BROWSER_USE_NAME
            ? "cancel"
            : "continue",
      });
      return;
    }

    thread.submit(undefined, {
      command: {
        resume: {
          type,
          message: "",
        },
      },
      onDisconnect:
        // @ts-ignore
        thread?.messages.at(-1).tool_calls?.[0]?.name === BROWSER_USE_NAME
          ? "cancel"
          : "continue",
    });
  };

  const toolCalls = ((message as any).tool_calls ?? []) as RenderToolCall[];

  const thinkToolCalls = toolCalls.filter(
    (toolCall) => toolCall.name === THINK_TOOL_NAME,
  );

  const visibleToolCalls = toolCalls.filter(
    (toolCall) => toolCall.name !== THINK_TOOL_NAME,
  );

  // Tool calls that actually produce a row in ToolCallsList: ask_questions and
  // response-widget-результаты (genui-виджеты, MCP-аппы, карточки планировщика)
  // рисуются самостоятельными блоками, поэтому не считаются. Когда таких нет,
  // reasoning/content рендерятся без обрамляющего tool-контейнера.
  const displayToolCalls = visibleToolCalls.filter((toolCall) => {
    const id = (toolCall as any).id as string | undefined;
    return (
      toolCall.name !== "ask_questions" &&
      !isResponseWidget(id ? resultsById?.[id] : undefined)
    );
  });
  const hasToolContainer = hasToolCalls && displayToolCalls.length > 0;

  const combinedReasoning = useMemo(() => {
    const parts: string[] = [];
    const reasoning = message.additional_kwargs?.reasoning_content;
    if (reasoning) parts.push(String(reasoning));
    for (const tc of thinkToolCalls) {
      const t = getThinkText(tc);
      if (t) parts.push(t);
    }
    if (inlineReasoning) parts.push(inlineReasoning);
    return normalizeReasoningText(parts.join("\n"));
  }, [
    message.additional_kwargs?.reasoning_content,
    thinkToolCalls,
    inlineReasoning,
  ]);

  const streamingThisMessage =
    !!thread?.isLoading && thread?.messages.at(-1)?.id === message.id;
  // Шаг с tool_calls считается "в работе", если он последний AI-шаг и поток
  // активен — даже если за ним уже летят tool-результаты.
  const stepInFlight = !!thread?.isLoading && isLastAi;

  return (
    <div
      style={
        noContainer ? undefined : { marginBottom: "20px", padding: "0 20px" }
      }
      onMouseEnter={() => setShowEdit(true)}
      onMouseLeave={() => setShowEdit(false)}
    >
      {edit ? (
        <MessageEditor
          message={message}
          onCancel={() => {
            setEdit(false);
            clear();
          }}
          thread={thread}
        />
      ) : (
        <>
          <div
            className={[
              "flex",
              noContainer ? "" : "py-2.5",
              message.type === "human" ? "justify-end" : "justify-start",
            ].join(" ")}
          >
            <div
              className={[
                message.type === "human"
                  ? "max-w-[80%] w-auto p-4 pt-4 pb-4 rounded-[25px] bg-secondary text-foreground overflow-x-auto"
                  : "max-w-full w-full p-0 bg-transparent",
                "markdown",
              ].join(" ")}
            >
              {hasToolContainer ? (
                <div
                  className={
                    noContainer
                      ? ""
                      : "rounded-md border border-border/40 bg-muted/20 p-2.5"
                  }
                >
                  {!hideContent && <ReasoningBlock text={combinedReasoning} />}
                  {!hideContent && normalizedContent?.trim() && (
                    <div className="mb-2">
                      <TextMarkdown isStreaming={streamingThisMessage}>
                        {normalizedContent}
                      </TextMarkdown>
                    </div>
                  )}
                  <ToolCallsList
                    toolCalls={visibleToolCalls as any}
                    resultsById={resultsById ?? {}}
                    isStreaming={stepInFlight}
                    thread={thread as any}
                  />
                </div>
              ) : (
                <>
                  {message.type === "ai" && combinedReasoning && (
                    <ReasoningBlock text={combinedReasoning} />
                  )}
                  <TextMarkdown isStreaming={streamingThisMessage}>
                    {normalizedContent}
                  </TextMarkdown>
                </>
              )}
              {message.type === "ai" &&
                leadingResponseWidgets &&
                leadingResponseWidgets.length > 0 && (
                  <div className="mt-3 flex flex-col gap-2">
                    {leadingResponseWidgets.map((w, i) => (
                      <ResponseWidget
                        key={w.toolCall.id ?? `lrw-${i}`}
                        item={w}
                        thread={thread}
                        isStreaming={!!thread?.isLoading}
                      />
                    ))}
                  </div>
                )}
              {message.type === "ai" &&
                answeredQuestions &&
                answeredQuestions.length > 0 && (
                  <div className="mt-3 flex flex-col gap-2">
                    {answeredQuestions.map((item) => (
                      <React.Suspense key={item.id} fallback={null}>
                        <AnsweredQuestionsCard data={item.data} />
                      </React.Suspense>
                    ))}
                  </div>
                )}
              {
                //@ts-ignore
                message.additional_kwargs &&
                //@ts-ignore
                message.additional_kwargs.selected &&
                //@ts-ignore
                Object.keys(message.additional_kwargs.selected).length > 0 ? (
                  <div className="mt-1 text-muted-foreground text-xs pointer-events-none">
                    Выбраны вложения:{" "}
                    {
                      //@ts-ignore
                      Object.keys(message.additional_kwargs.selected).length
                    }
                  </div>
                ) : (
                  <></>
                )
              }
            </div>
          </div>
          {isCurrentInterruptMessage && (
            <motion.div
              layout
              className="mt-1 mb-2 flex w-full justify-end pr-2 items-center gap-2"
            >
              {isDestructiveConfirm && (
                <span className="mr-auto text-xs font-medium text-red-600">
                  ⚠️ Подтвердите {destructiveLabel}
                </span>
              )}
              <motion.button
                layout
                animate={{
                  backgroundPosition: ["0% 0%", "100% 100%"],
                }}
                transition={{
                  layout: {
                    type: "spring",
                    stiffness: 500,
                    damping: 35,
                  },
                  backgroundPosition: {
                    duration: 2.8,
                    repeat: Infinity,
                    repeatType: "mirror",
                    ease: "linear",
                  },
                }}
                onClick={() => void handleInterruptAction("comment")}
                disabled={thread?.isLoading || isApprovalLoading}
                title="Отменить выполнение"
                style={{
                  backgroundImage:
                    "linear-gradient(135deg, #dc2626, #ef4444, #b91c1c)",
                  backgroundSize: "220% 220%",
                }}
                className="w-9 h-9 p-0 rounded-full text-white flex items-center justify-center transition-[filter] hover:brightness-110 disabled:opacity-67"
              >
                <X />
              </motion.button>
              <AnimatePresence mode="popLayout">
                <motion.button
                  key="approve-inline-btn"
                  layout
                  initial={{ x: 24, scale: 1, opacity: 1 }}
                  animate={{
                    x: 0,
                    scale: 1,
                    opacity: 1,
                    backgroundPosition: ["0% 0%", "100% 100%"],
                  }}
                  exit={{ x: 24, scale: 1, opacity: 1 }}
                  transition={{
                    layout: {
                      type: "spring",
                      stiffness: 500,
                      damping: 35,
                    },
                    x: {
                      type: "spring",
                      stiffness: 500,
                      damping: 35,
                    },
                    backgroundPosition: {
                      duration: 2.8,
                      repeat: Infinity,
                      repeatType: "mirror",
                      ease: "linear",
                    },
                  }}
                  onClick={() => void handleInterruptAction("approve")}
                  disabled={thread?.isLoading || isApprovalLoading}
                  title="Подтвердить выполнение"
                  style={{
                    backgroundImage:
                      "linear-gradient(135deg, #16a34a, #22c55e, #15803d)",
                    backgroundSize: "220% 220%",
                  }}
                  className="w-9 h-9 p-0 rounded-full text-white flex items-center justify-center transition-[filter] hover:brightness-110 disabled:opacity-67"
                >
                  {isApprovalLoading ? (
                    <RefreshCw className="size-4 animate-spin" />
                  ) : (
                    <Check />
                  )}
                </motion.button>
              </AnimatePresence>
            </motion.div>
          )}
          {
            //@ts-ignore
            message.additional_kwargs &&
            //@ts-ignore
            message.additional_kwargs.files?.length ? (
              <div style={{ marginBottom: "8px" }}>
                <MessageAttachments message={message} />
              </div>
            ) : (
              <></>
            )
          }
          <div
            className={[
              "flex flex-grow-0 gap-2 transition-opacity duration-200",
              showEdit && !hideActions ? "opacity-100" : "opacity-0",
              hideActions ? "pointer-events-none h-0 overflow-hidden" : "",
              message.type === "ai" ? "justify-start" : "justify-end",
            ].join(" ")}
          >
            {message.type === "human" && (
              <button
                disabled={
                  !thread || thread.isLoading || branches.initialLoading
                }
                onClick={() => {
                  setEdit(true);
                  if (
                    //@ts-ignore
                    message.additional_kwargs &&
                    //@ts-ignore
                    message.additional_kwargs.selected &&
                    //@ts-ignore
                    Object.keys(message.additional_kwargs.selected).length > 0
                  )
                    // @ts-ignore
                    setSelectedAttachments(message.additional_kwargs.selected);
                  else clear();
                }}
                className="transition-transform duration-200 bg-transparent border-0 text-foreground p-0 disabled:opacity-50 cursor-pointer hover:scale-110 disabled:hover:scale-100"
              >
                <Pencil size={16} />
              </button>
            )}
            {message.type === "ai" && !rawHasToolCalls && (
              <>
                <button
                  disabled={
                    !thread || thread.isLoading || branches.initialLoading
                  }
                  onClick={onRefresh}
                  className="transition-transform duration-200 cursor-pointer bg-transparent border-0 text-foreground p-0 disabled:opacity-50 cursor-pointer hover:scale-110 disabled:hover:scale-100"
                >
                  <RefreshCw size={16} />
                </button>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <button
                      disabled={isExporting}
                      className="transition-transform duration-200 cursor-pointer bg-transparent border-0 text-foreground p-0 disabled:opacity-50 hover:scale-110 disabled:hover:scale-100"
                      title="Скачать"
                    >
                      <Download size={16} />
                    </button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="start">
                    <DropdownMenuItem onSelect={() => handleExport("pdf")}>
                      PDF
                    </DropdownMenuItem>
                    <DropdownMenuItem onSelect={() => handleExport("docx")}>
                      DOCX
                    </DropdownMenuItem>
                    <DropdownMenuItem onSelect={() => handleExport("md")}>
                      Markdown
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </>
            )}
            <BranchSwitcher thread={thread} message={message} />
          </div>
        </>
      )}
    </div>
  );
};

export default React.memo(
  Message,
  (prev, next) =>
    prev.message === next.message &&
    prev.thread === next.thread &&
    prev.resultsById === next.resultsById &&
    prev.isLastAi === next.isLastAi &&
    prev.isLast === next.isLast &&
    prev.noContainer === next.noContainer &&
    prev.hideActions === next.hideActions &&
    prev.hideToolCalls === next.hideToolCalls &&
    prev.hideContent === next.hideContent &&
    prev.leadingResponseWidgets === next.leadingResponseWidgets &&
    prev.answeredQuestions === next.answeredQuestions,
);
