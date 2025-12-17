import React, {
  useState,
  useRef,
  useEffect,
  useCallback,
  useMemo,
} from "react";
import { HumanMessage } from "@langchain/langgraph-sdk";
import {
  Check,
  Paperclip,
  Send,
  X,
  Settings2,
  Brain,
  Files,
  Cog,
} from "lucide-react";
import { useSettings } from "./Settings.tsx";
import { useFileUpload, UploadedFile } from "../hooks/useFileUploads";
import { useSelectedAttachments } from "../hooks/SelectedAttachmentsContext.tsx";
import {
  AttachmentBubble,
  AttachmentsContainer,
  CircularProgress,
  CloseButton,
  EnlargedImage,
  ImagePreview,
  Overlay,
  ProgressOverlay,
  RemoveButton,
} from "./Attachments.tsx";
import { FileData, GraphState, GraphTemplate } from "../interfaces.ts";
import { BROWSER_USE_NAME } from "../config.ts";
import { UseStream } from "@langchain/langgraph-sdk/react";
import { useRagContext } from "@/components/rag/providers/RAG.tsx";
import Spinner from "./Spinner.tsx";
import { AnimatePresence, motion } from "framer-motion";
import { useUserInfo } from "@/components/providers/user-info.tsx";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

const MAX_TEXTAREA_HEIGHT = 200; // макс высота в px

// Прочие стили для превью и оверлея оставляем без изменений...

interface InputAreaProps {
  thread?: UseStream<GraphState, GraphTemplate>;
}

const InputArea: React.FC<InputAreaProps> = ({ thread }) => {
  const [message, setMessage] = useState("");
  const [enlargedImage, setEnlargedImage] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const { uploads, uploadFiles, removeUpload, resetUploads } = useFileUpload();
  const { selected, clear } = useSelectedAttachments();
  const autoApproveLockRef = useRef<unknown>(null);
  const [isMCPLoading, setIsMCPLoading] = useState(false);

  const { collections, activeCollections } = useRagContext();
  const { settings } = useSettings();
  const { mcpTools, openMcpModal, openContextModal, openCollectionsModal } =
    useUserInfo();

  const enabledCollections = useMemo(() => {
    const active = Object.keys(activeCollections).filter(
      (key) => activeCollections[key],
    );
    return collections.filter((collection) => active.includes(collection.uuid));
  }, [activeCollections, collections]);

  const mcpToolsPayload = useMemo(
    () =>
      mcpTools.map((tool) => ({
        name: tool.name,
        description: tool.description,
        inputSchema: tool.inputSchema,
      })),
    [mcpTools],
  );

  const selectedCount = Object.keys(selected).length;

  const isUploading = uploads.some((u) => u.progress < 100 && !u.error);
  const handleSendMessage = useCallback(
    async (content: string, files?: FileData[]) => {
      const newMessage = {
        type: "human",
        content: content,
        additional_kwargs: {
          user_input: content,
          files: files,
          selected: selected,
        },
      } as HumanMessage;
      clear();
      thread?.submit(
        {
          messages: [newMessage],
          collections: enabledCollections,
          mcp_tools: mcpToolsPayload,
          secrets: settings.contextSecrets,
          instructions: settings.contextInstructions,
        },
        {
          optimisticValues(prev) {
            const prevMessages = prev.messages ?? [];
            const newMessages = [...prevMessages, newMessage];
            return { ...prev, messages: newMessages };
          },
          streamMode: ["messages"],
          onDisconnect: "continue",
        },
      );
    },
    [
      thread,
      selected,
      clear,
      mcpToolsPayload,
      enabledCollections,
      settings.contextInstructions,
      settings.contextSecrets,
    ],
  );
  const handleContinueThread = useCallback(
    async (data: any) => {
      thread?.submit(undefined, {
        command: { resume: data },
        optimisticValues(prev) {
          if (!data.message) return {};
          const prevMessages = prev.messages ?? [];
          const newMessages = [
            ...prevMessages,
            {
              type: "tool",
              content: `"<decline>${data.message}</decline>"`,
            },
          ];
          return { ...prev, messages: newMessages };
        },
        onDisconnect:
          // @ts-ignore
          thread?.messages.at(-1).tool_calls[0]?.name === BROWSER_USE_NAME
            ? "cancel"
            : "continue",
      });
    },
    [thread],
  );

  // автоподгон высоты
  const autoResize = () => {
    const el = textRef.current;
    if (!el) return;
    el.style.height = "auto";
    const newHeight = Math.min(el.scrollHeight, MAX_TEXTAREA_HEIGHT);
    el.style.height = `${newHeight}px`;
  };

  // при первом рендере и при очистке
  useEffect(() => {
    autoResize();
  }, [message]);

  const handleContinue = useCallback(
    async (type: "comment" | "approve") => {
      if (
        thread?.interrupt?.value?.type === "tool_call" &&
        thread?.interrupt?.value?.args &&
        thread?.interrupt?.value?.tool_name &&
        !message
      ) {
        const tool = mcpTools.find(
          (t) => t.name === thread.interrupt?.value?.tool_name,
        );
        if (tool) {
          setIsMCPLoading(true);
          tool
            .callTool(thread.interrupt.value.args)
            .then((result) => {
              void handleContinueThread({ type, result });
            })
            // @ts-ignore
            .catch((reason) => {
              void handleContinueThread({
                type: "comment",
                message:
                  "Не удалось подключиться к MCP. Попроси пользователя проверить подключение " +
                  (reason ? reason : ""),
              });
            })
            .finally(() => {
              setIsMCPLoading(false);
            });
        } else {
          void handleContinueThread({
            type: "comment",
            message:
              "Не удалось найти нужный MCP. Попроси пользователя проверить подключенные MCP",
          });
        }
      } else {
        void handleContinueThread({ type, message });
      }
      setMessage("");
    },
    [mcpTools, setMessage, handleContinueThread, message, thread?.interrupt],
  );

  useEffect(() => {
    const canAutoApprove =
      !!thread?.interrupt &&
      ["approve", "tool_call"].includes(thread?.interrupt.value?.type ?? "") &&
      settings.autoApprove;

    const interruptKey = thread?.interrupt?.value;

    if (!canAutoApprove) {
      autoApproveLockRef.current = null;
      return;
    }

    if (autoApproveLockRef.current === interruptKey) return;

    if (thread?.isLoading || isMCPLoading) return;

    autoApproveLockRef.current = interruptKey;
    void handleContinue("approve");
  }, [
    thread?.interrupt,
    thread?.interrupt?.value,
    thread?.isLoading,
    isMCPLoading,
    settings.autoApprove,
    handleContinue,
  ]);

  const handleSend = () => {
    if (!message.trim() && uploads.length === 0) return;
    const attachments = uploads.map((u) => u.data).filter(Boolean);
    void handleSendMessage(message, attachments as any);
    setMessage("");
    resetUploads();
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (!thread?.isLoading && !isUploading) {
        if (thread?.interrupt) {
          void handleContinue(message ? "comment" : "approve");
        } else {
          handleSend();
        }
      }
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      uploadFiles(Array.from(e.target.files));
      e.target.value = "";
    }
  };

  return (
    <div className="p-4 bg-card dark:bg-input border-border rounded-lg shadow-[2px_2px_12px_6px_rgba(0,0,0,0.04)] dark:shadow-[2px_2px_12px_6px_rgba(0,0,0,0.14)] print:hidden border-t-1 border-highlight">
      <div className="flex items-end gap-2 relative">
        <input
          className="hidden"
          type="file"
          ref={fileInputRef}
          onChange={handleFileChange}
          multiple
          disabled={thread?.isLoading || isMCPLoading}
        />
        <div className="flex flex-col items-center gap-1">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                disabled={thread?.isLoading || isMCPLoading}
                title="Открыть настройки"
                className="w-9 h-9 p-0 rounded-full text-foreground flex items-center justify-center transition-colors cursor-pointer outline-hidden disabled:opacity-67"
              >
                <Settings2 />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" sideOffset={3}>
              <DropdownMenuItem onSelect={openContextModal}>
                <Brain className={"size-5"} />
                <span>Контекст</span>
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={openMcpModal}>
                <Cog className={"size-5"} />
                <span>Инструменты</span>
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={openCollectionsModal}>
                <Files className={"size-5"} />
                <span>Знания</span>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={thread?.isLoading || isMCPLoading}
            title="Добавить вложения"
            className="w-9 h-9 p-0 rounded-full text-foreground flex items-center justify-center transition-colors cursor-pointer outline-hidden disabled:opacity-67"
          >
            <Paperclip />
          </button>
        </div>

        <textarea
          placeholder={
            thread?.interrupt
              ? "Принять / Отменить с комментарием…"
              : "Введите вашу задачу…"
          }
          ref={textRef}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={thread?.isLoading || isMCPLoading}
          className="flex-1 min-h-[76px] max-h-[200px] resize-none font-sans p-3 rounded-md text-foreground placeholder:text-muted-foreground overflow-y-auto outline-none border-0 disabled:opacity-60"
        />
        {thread?.interrupt &&
        thread?.interrupt.value &&
        ["approve", "tool_call"].includes(thread.interrupt.value.type) &&
        (!settings.autoApprove ||
          thread.interrupt.value.type === "tool_call") ? (
          <>
            {isMCPLoading ? (
              <div className="w-9 h-9 flex items-center justify-center">
                <Spinner size="16" />
              </div>
            ) : (
              <>
                <motion.div layout className="flex items-center gap-2">
                  <motion.button
                    layout
                    transition={{ type: "spring", stiffness: 500, damping: 35 }}
                    onClick={() => handleContinue("comment")}
                    disabled={thread.isLoading || isMCPLoading}
                    title="Отменить выполнение"
                    className="w-9 h-9 p-0 rounded-full bg-red-600 text-white flex items-center justify-center transition-colors hover:bg-red-700 disabled:opacity-67"
                  >
                    <X />
                  </motion.button>
                  <AnimatePresence mode="popLayout">
                    {!message.trim() && (
                      <motion.button
                        key="approve-btn"
                        layout
                        initial={{ x: 24, scale: 1, opacity: 1 }}
                        animate={{ x: 0, scale: 1, opacity: 1 }}
                        exit={{ x: 24, scale: 1, opacity: 1 }}
                        transition={{
                          type: "spring",
                          stiffness: 500,
                          damping: 35,
                        }}
                        onClick={() => handleContinue("approve")}
                        disabled={thread.isLoading || isMCPLoading}
                        title="Подтвердить выполнение"
                        className="w-9 h-9 p-0 rounded-full bg-green-600 text-white flex items-center justify-center transition-colors hover:bg-green-700 disabled:opacity-67"
                      >
                        <Check />
                      </motion.button>
                    )}
                  </AnimatePresence>
                </motion.div>
              </>
            )}
          </>
        ) : (
          <button
            type="button"
            onClick={handleSend}
            disabled={
              thread?.isLoading ||
              isMCPLoading ||
              !message.trim() ||
              isUploading
            }
            title="Отправить"
            className="w-9 h-9 p-0 rounded-full text-foreground flex items-center justify-center transition-colors cursor-pointer outline-hidden disabled:opacity-67"
          >
            <Send />
          </button>
        )}
      </div>

      {uploads.length > 0 && (
        <AttachmentsContainer>
          {uploads.map((u: UploadedFile, idx) => (
            <AttachmentBubble
              key={idx}
              onClick={() => u.previewUrl && setEnlargedImage(u.previewUrl!)}
            >
              {u.previewUrl ? (
                <ImagePreview src={u.previewUrl} />
              ) : (
                <span>{u.file.name}</span>
              )}

              {u.progress < 100 && (
                <ProgressOverlay>
                  <CircularProgress progress={u.progress}>
                    {u.progress}%
                  </CircularProgress>
                </ProgressOverlay>
              )}

              <RemoveButton
                onClick={(e) => {
                  e.stopPropagation();
                  removeUpload(idx);
                }}
              >
                ×
              </RemoveButton>
            </AttachmentBubble>
          ))}
        </AttachmentsContainer>
      )}

      <div
        className={[
          "absolute bottom-2 left-[75px] text-muted-foreground text-xs pointer-events-none transition-opacity duration-100",
          selectedCount > 0
            ? "opacity-100 translate-y-0"
            : "opacity-0 translate-y-1",
        ].join(" ")}
      >
        Выбрано вложений: {selectedCount}
      </div>

      {enlargedImage && (
        <Overlay onClick={() => setEnlargedImage(null)}>
          <EnlargedImage src={enlargedImage} />
          <CloseButton onClick={() => setEnlargedImage(null)}>×</CloseButton>
        </Overlay>
      )}
    </div>
  );
};

export default InputArea;
