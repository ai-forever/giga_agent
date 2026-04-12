import React, { useEffect, useMemo, useRef, useState } from "react";
import { Checkpoint, Message as Message_ } from "@langchain/langgraph-sdk";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { vscDarkPlus } from "react-syntax-highlighter/dist/esm/styles/prism";
import MessageAttachments from "./MessageAttachments.tsx";
import { TOOL_MAP } from "../config.ts";
import type { UseStream } from "@langchain/langgraph-sdk/react";
import { GraphState, GraphTemplate } from "../interfaces.ts";
import MessageEditor from "./MessageEditor.tsx";
import {
  Check,
  ChevronLeft,
  ChevronRight,
  Pencil,
  RefreshCw,
  X,
} from "lucide-react";
import { useSelectedAttachments } from "../hooks/SelectedAttachmentsContext.tsx";
import TextMarkdown from "./attachments/TextMarkdown.tsx";
import { AnimatePresence, motion } from "framer-motion";
import { useUserInfo } from "@/components/providers/user-info.tsx";
import { BROWSER_USE_NAME } from "@/config.ts";

function BranchSwitcher({
  thread,
  message,
}: {
  thread?: UseStream<GraphState, GraphTemplate>;
  message: Message_;
}) {
  if (!thread) return null;
  const meta = thread.getMessagesMetadata(message);
  const branch = meta?.branch;
  const branchOptions = meta?.branchOptions;
  if (!branchOptions || !branch) return null;
  const onSelect = (branch: any) => thread.setBranch(branch);
  const index = branchOptions.indexOf(branch);

  return (
    <div className="flex items-center gap-2">
      <button
        onClick={() => {
          const prevBranch = branchOptions[index - 1];
          if (!prevBranch) return;
          onSelect(prevBranch);
        }}
        disabled={thread.isLoading}
        className="transition-transform duration-200 bg-transparent border-0 text-foreground p-0 disabled:opacity-50 cursor-pointer hover:scale-110 disabled:hover:scale-100"
      >
        <ChevronLeft size={16} />
      </button>
      <span className="text-[13px]">
        {index + 1} / {branchOptions.length}
      </span>
      <button
        onClick={() => {
          const nextBranch = branchOptions[index + 1];
          if (!nextBranch) return;
          onSelect(nextBranch);
        }}
        disabled={thread.isLoading}
        className="transition-transform duration-200 bg-transparent border-0 text-foreground p-0 disabled:opacity-50 cursor-pointer hover:scale-110 disabled:hover:scale-100"
      >
        <ChevronRight size={16} />
      </button>
    </div>
  );
}

interface MessageProps {
  message: Message_;
  onWrite: () => void;
  onWriteEnd?: () => void;
  writeMessage?: boolean;
  thread?: UseStream<GraphState, GraphTemplate>;
}

const Message: React.FC<MessageProps> = ({
  message,
  onWrite,
  onWriteEnd,
  thread,
  writeMessage = false,
}) => {
  // 2) хук для постепенной «печати» чанков
  const displayedRef = useRef<string>(""); // накапливаемый текст
  const [displayed, setDisplayed] = useState<string>("");
  const [edit, setEdit] = useState<boolean>(false);
  const [showEdit, setShowEdit] = useState<boolean>(false);
  const [isApprovalLoading, setIsApprovalLoading] = useState(false);
  const { setSelectedAttachments, clear } = useSelectedAttachments();
  const { mcpTools } = useUserInfo();

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
  const normalizedContent = useMemo(() => {
    let md = displayed ?? "";

    // 1) перед каждым ``` вставляем гарантированно пустую строку
    md = md.replace(/(^|\n)(```[^\n]*)/g, "$1\n$2");
    md = md.replace(
      /<thinking>([\s\S]*?)<\/thinking>/g,
      (_, content) =>
        `<thinking>${content.replace(/\n/g, "<br>")}</thinking>\n`,
    );
    // md = md.replace(/\$\\?([^\$]+)\$/g, "\n$$$$$1$$$$\n");
    return md;
  }, [displayed]);

  useEffect(() => {
    onWrite();
  }, [normalizedContent, onWrite]);

  const onRefresh = () => {
    const parentMessage = thread?.messages.filter(
      (_: Message_, i: number) =>
        i + 1 < thread.messages.length &&
        thread.messages[i + 1].id === message.id,
    ); // Получаем сообщение которое идет до AI сообщения
    // TODO: Сейчас это нужно, чтобы giga_agent адекватно работал с aegra, так как в их API нельзя просто передавать checkpoint (без input)
    const meta = thread?.getMessagesMetadata(message);
    const parentCheckpoint = meta?.branch
      ? ({
          ...meta?.firstSeenState?.parent_checkpoint,
          thread_id: meta.firstSeenState?.checkpoint.thread_id,
          checkpoint_id:
            meta.branch.split(">").length > 1
              ? meta.branch.split(">")[0]
              : meta.branch,
        } as Checkpoint)
      : meta?.firstSeenState?.parent_checkpoint;

    thread?.submit(
      { messages: parentMessage },
      { checkpoint: parentCheckpoint },
    );
  };

  const isCurrentInterruptMessage =
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

  return (
    <div
      style={{ marginBottom: "20px", padding: "0 20px" }}
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
              "flex py-2.5",
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
              <TextMarkdown>{normalizedContent}</TextMarkdown>

              {
                // @ts-ignore
                message.tool_calls &&
                  // @ts-ignore
                  message.tool_calls.map((tool_call, index) => (
                    <div key={index} className="mt-2">
                      <div>
                        Действие:{" "}
                        {tool_call.name in TOOL_MAP
                          ? // @ts-ignore
                            `${TOOL_MAP[tool_call.name]} `
                          : tool_call.name}
                      </div>
                      <SyntaxHighlighter
                        language={
                          tool_call.name === "python" ? "python" : "json"
                        }
                        style={vscDarkPlus}
                      >
                        {tool_call.name === "python"
                          ? tool_call.args.code
                          : JSON.stringify(tool_call.args)}
                      </SyntaxHighlighter>
                    </div>
                  ))
              }
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
              showEdit ? "opacity-100" : "opacity-0",
              message.type === "ai" ? "justify-start" : "justify-end",
            ].join(" ")}
          >
            {message.type === "human" && (
              <button
                disabled={!thread || thread.isLoading}
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
            {message.type === "ai" && (
              <button
                disabled={!thread || thread.isLoading}
                onClick={onRefresh}
                className="transition-transform duration-200 cursor-pointer bg-transparent border-0 text-foreground p-0 disabled:opacity-50 cursor-pointer hover:scale-110 disabled:hover:scale-100"
              >
                <RefreshCw size={16} />
              </button>
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
  (prev, next) => prev.message === next.message && prev.thread === next.thread,
);
