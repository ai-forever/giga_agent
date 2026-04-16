import React, {
  useState,
  useRef,
  useEffect,
  useCallback,
  useMemo,
} from "react";
import { HumanMessage } from "@langchain/langgraph-sdk";
import {
  Paperclip,
  Send,
  Settings2,
  Brain,
  Files,
  Cog,
  Printer,
  Mic,
  Loader2,
} from "lucide-react";
import { useSettings } from "./Settings.tsx";
import { useFileUpload, UploadedFile } from "../hooks/useFileUploads";
import { apiClient, ApiError } from "../lib/api-client.ts";
import { API_AGENT_PREFIX } from "../config.ts";
import { toast } from "sonner";
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
import { useUserInfo } from "@/components/providers/user-info.tsx";
import { useAuth } from "@/components/providers/auth.tsx";
import { Switch } from "@/components/ui/switch";
import { useNavigate } from "react-router-dom";
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
  const navigate = useNavigate();
  const [message, setMessage] = useState("");
  const [isMobileDevice, setIsMobileDevice] = useState(false);
  const [enlargedImage, setEnlargedImage] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const dragCounterRef = useRef(0);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const { uploads, uploadFiles, removeUpload, resetUploads } = useFileUpload();
  const { selected, clear } = useSelectedAttachments();
  const autoApproveLockRef = useRef<unknown>(null);
  const [isMCPLoading, setIsMCPLoading] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [micSupported, setMicSupported] = useState(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const recordedChunksRef = useRef<Blob[]>([]);
  const cancelRecordingRef = useRef(false);

  const {
    collections,
    activeCollections,
    getCollections,
    initialSearchExecuted,
    initialFetch,
  } = useRagContext();
  const { settings, setSettings } = useSettings();
  const { user } = useAuth();
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
      const userSettings = (user?.settings ?? {}) as Record<string, unknown>;
      const contextInstructions =
        typeof userSettings.contextInstructions === "string"
          ? userSettings.contextInstructions
          : "";
      const contextSecrets = Array.isArray(userSettings.contextSecrets)
        ? userSettings.contextSecrets
        : [];
      clear();
      thread?.submit(
        {
          messages: [newMessage],
          collections: enabledCollections,
          mcp_tools: mcpToolsPayload,
          secrets: contextSecrets,
          instructions: contextInstructions,
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
    [thread, selected, clear, mcpToolsPayload, enabledCollections, user],
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

  useEffect(() => {
    if (!window.matchMedia) return;

    const media = window.matchMedia("(pointer: coarse)");
    const updateIsMobileDevice = () => setIsMobileDevice(media.matches);

    updateIsMobileDevice();
    media.addEventListener("change", updateIsMobileDevice);

    return () => media.removeEventListener("change", updateIsMobileDevice);
  }, []);

  useEffect(() => {
    const supported =
      typeof navigator !== "undefined" &&
      !!navigator.mediaDevices?.getUserMedia &&
      typeof window.MediaRecorder !== "undefined";
    setMicSupported(supported);
  }, []);

  useEffect(() => {
    return () => {
      mediaStreamRef.current?.getTracks().forEach((t) => t.stop());
      mediaStreamRef.current = null;
      mediaRecorderRef.current = null;
    };
  }, []);

  const insertAtCursor = useCallback((text: string) => {
    const trimmed = text.trim();
    if (!trimmed) return;
    const el = textRef.current;
    setMessage((prev) => {
      const start = el?.selectionStart ?? prev.length;
      const end = el?.selectionEnd ?? prev.length;
      const before = prev.slice(0, start);
      const after = prev.slice(end);
      const needsLeadingSpace = before.length > 0 && !/\s$/.test(before);
      const needsTrailingSpace = after.length > 0 && !/^\s/.test(after);
      const insertion =
        (needsLeadingSpace ? " " : "") +
        trimmed +
        (needsTrailingSpace ? " " : "");
      const next = before + insertion + after;
      requestAnimationFrame(() => {
        const caret = before.length + insertion.length;
        if (el) {
          el.focus();
          try {
            el.setSelectionRange(caret, caret);
          } catch {
            /* selection may fail if unmounted */
          }
        }
      });
      return next;
    });
  }, []);

  const teardownRecording = useCallback(() => {
    mediaStreamRef.current?.getTracks().forEach((t) => t.stop());
    mediaStreamRef.current = null;
    mediaRecorderRef.current = null;
    recordedChunksRef.current = [];
  }, []);

  const startRecording = useCallback(async () => {
    if (isRecording || isTranscribing || !micSupported) return;
    if (thread?.isLoading || isMCPLoading) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaStreamRef.current = stream;
      const candidates = [
        "audio/webm;codecs=opus",
        "audio/ogg;codecs=opus",
        "audio/webm",
        "audio/mp4",
      ];
      const mimeType = candidates.find((c) =>
        typeof MediaRecorder.isTypeSupported === "function"
          ? MediaRecorder.isTypeSupported(c)
          : false,
      );
      const rec = mimeType
        ? new MediaRecorder(stream, { mimeType })
        : new MediaRecorder(stream);
      recordedChunksRef.current = [];
      rec.addEventListener("dataavailable", (e) => {
        if (e.data && e.data.size > 0) recordedChunksRef.current.push(e.data);
      });
      mediaRecorderRef.current = rec;
      cancelRecordingRef.current = false;
      rec.start();
      setIsRecording(true);
    } catch {
      teardownRecording();
      setIsRecording(false);
    }
  }, [
    isRecording,
    isTranscribing,
    micSupported,
    thread?.isLoading,
    isMCPLoading,
    teardownRecording,
  ]);

  const finishRecording = useCallback(
    async (cancelled: boolean) => {
      const rec = mediaRecorderRef.current;
      if (!rec) {
        setIsRecording(false);
        return;
      }
      const blob = await new Promise<Blob>((resolve) => {
        const handle = () => {
          const b = new Blob(recordedChunksRef.current, {
            type: rec.mimeType || "audio/webm",
          });
          resolve(b);
        };
        rec.addEventListener("stop", handle, { once: true });
        if (rec.state !== "inactive") {
          try {
            rec.stop();
          } catch {
            handle();
          }
        } else {
          handle();
        }
      });
      const mime = rec.mimeType || "audio/webm";
      teardownRecording();
      setIsRecording(false);

      if (cancelled || blob.size === 0) return;

      setIsTranscribing(true);
      try {
        const form = new FormData();
        const ext = mime.includes("ogg")
          ? "ogg"
          : mime.includes("mp4")
            ? "m4a"
            : "webm";
        form.append("audio", blob, `record.${ext}`);
        const res = await apiClient.post<{ text: string }>(
          `${API_AGENT_PREFIX}/stt/recognize`,
          form,
          { attachAuth: true, showError: false },
        );
        if (res?.text) insertAtCursor(res.text);
        else {
          toast.warning("Речь не распознана", {
            description: "Попробуй ещё раз, говори чуть громче.",
            richColors: true,
          });
        }
      } catch (err) {
        const detail =
          err instanceof ApiError ? err.message : "Не удалось распознать речь";
        toast.error("Распознавание не удалось", {
          description: detail,
          richColors: true,
        });
      } finally {
        setIsTranscribing(false);
      }
    },
    [teardownRecording, insertAtCursor],
  );

  const stopRecording = useCallback(() => {
    if (!isRecording) return;
    const cancelled = cancelRecordingRef.current;
    cancelRecordingRef.current = false;
    void finishRecording(cancelled);
  }, [isRecording, finishRecording]);

  const cancelRecording = useCallback(() => {
    if (!isRecording) return;
    cancelRecordingRef.current = true;
    void finishRecording(true);
  }, [isRecording, finishRecording]);

  const handleContinue = useCallback(
    async (type: "comment" | "approve") => {
      if (
        thread?.interrupt?.value?.type === "tool_call" &&
        thread?.interrupt?.value?.tools &&
        !message
      ) {
        const mcpToolMap = Object.fromEntries(
          mcpTools.map((tool) => [tool.name, tool]),
        );
        const toolCalls = thread?.interrupt?.value?.tools;
        if (toolCalls) {
          setIsMCPLoading(true);
          const promises = toolCalls.map((call) =>
            mcpToolMap[call.name].callTool(call.args),
          );
          const results = await Promise.all(
            promises.map((p) => p.catch((e) => e)),
          );
          void handleContinueThread({
            type,
            results: results.map((result, index) => ({
              result,
              id: toolCalls[index].id,
            })),
          });
          setIsMCPLoading(false);
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
    if (isMobileDevice) return;

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

  const isBusy = thread?.isLoading || isMCPLoading;

  const handlePaste = useCallback(
    (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
      if (isBusy) return;
      const items = e.clipboardData?.items;
      if (!items) return;
      const files: File[] = [];
      for (let i = 0; i < items.length; i++) {
        const item = items[i];
        if (item.kind === "file") {
          const file = item.getAsFile();
          if (file) files.push(file);
        }
      }
      if (files.length > 0) {
        e.preventDefault();
        uploadFiles(files);
      }
    },
    [uploadFiles, isBusy],
  );

  const handleDragEnter = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      if (isBusy) return;
      if (!Array.from(e.dataTransfer?.types ?? []).includes("Files")) return;
      e.preventDefault();
      dragCounterRef.current += 1;
      setIsDragging(true);
    },
    [isBusy],
  );

  const handleDragOver = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      if (isBusy) return;
      if (!Array.from(e.dataTransfer?.types ?? []).includes("Files")) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "copy";
    },
    [isBusy],
  );

  const handleDragLeave = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      if (isBusy) return;
      e.preventDefault();
      dragCounterRef.current = Math.max(0, dragCounterRef.current - 1);
      if (dragCounterRef.current === 0) setIsDragging(false);
    },
    [isBusy],
  );

  const handleDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      if (isBusy) return;
      e.preventDefault();
      dragCounterRef.current = 0;
      setIsDragging(false);
      const files = Array.from(e.dataTransfer?.files ?? []);
      if (files.length > 0) uploadFiles(files);
    },
    [uploadFiles, isBusy],
  );

  const handleOpenDocuments = useCallback(async () => {
    if (collections.length > 0) {
      openCollectionsModal();
      return;
    }

    if (!initialSearchExecuted) {
      await initialFetch();
    }

    const latestCollections = await getCollections().catch(() => []);
    if (latestCollections.length > 0) {
      openCollectionsModal();
      return;
    }

    navigate("/rag");
  }, [
    collections.length,
    getCollections,
    initialFetch,
    initialSearchExecuted,
    navigate,
    openCollectionsModal,
  ]);

  return (
    <div className="bg-card w-full sticky bottom-0 p-5 pt-0 max-[900px]:p-0 z-9">
      <div className="relative max-w-[900px] mx-auto">
        <label
          data-onboarding="autonomy-switch"
          className="absolute -top-5 right-2 flex items-center gap-2 select-none text-[11px] text-muted-foreground leading-none z-20 bg-card/80 rounded px-1"
        >
          <span>Автономность</span>
          <Switch
            checked={settings.autoApprove ?? false}
            onCheckedChange={(checked) =>
              setSettings((prev) => ({ ...prev, autoApprove: checked }))
            }
          />
        </label>
        <div
          className="relative p-4 bg-card dark:bg-input border-border rounded-lg print:hidden border-1 border-highlight overflow-hidden"
          onDragEnter={handleDragEnter}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
        >
          {isDragging && (
            <div className="absolute inset-0 z-10 flex items-center justify-center rounded-lg border-2 border-dashed border-primary bg-card/90 dark:bg-input/90 pointer-events-none text-sm text-foreground">
              Отпустите, чтобы прикрепить файлы
            </div>
          )}
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
                    data-onboarding="gear-menu-btn"
                    type="button"
                    disabled={thread?.isLoading || isMCPLoading}
                    title="Открыть настройки"
                    className="w-9 h-9 p-0 rounded-full text-foreground flex items-center justify-center transition-colors cursor-pointer outline-hidden disabled:opacity-67"
                  >
                    <Settings2 />
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent
                  className="input-dropdown"
                  align="start"
                  sideOffset={3}
                >
                  <DropdownMenuItem onSelect={openContextModal}>
                    <Brain className={"size-5"} />
                    <span>Персонализация</span>
                  </DropdownMenuItem>
                  <DropdownMenuItem onSelect={openMcpModal}>
                    <Cog className={"size-5"} />
                    <span>Инструменты</span>
                  </DropdownMenuItem>
                  <DropdownMenuItem onSelect={() => void handleOpenDocuments()}>
                    <Files className={"size-5"} />
                    <span>Документы</span>
                  </DropdownMenuItem>
                  <DropdownMenuItem onSelect={() => window.print()}>
                    <Printer className={"size-5"} />
                    <span>Печать</span>
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
              <button
                data-onboarding="attachments-btn"
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
              data-onboarding="chat-input"
              placeholder={
                thread?.interrupt
                  ? "Принять / Отменить с комментарием…"
                  : "Введите вашу задачу…"
              }
              ref={textRef}
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              onKeyDown={handleKeyDown}
              onPaste={handlePaste}
              disabled={thread?.isLoading || isMCPLoading}
              className="flex-1 min-h-[76px] max-h-[200px] resize-none font-sans p-3 rounded-md text-foreground placeholder:text-muted-foreground overflow-y-auto outline-none border-0 disabled:opacity-60"
            />
            <div className="flex flex-col items-end gap-1">
              {micSupported && (
                <button
                  type="button"
                  onMouseDown={(e) => {
                    e.preventDefault();
                    void startRecording();
                  }}
                  onMouseUp={(e) => {
                    e.preventDefault();
                    stopRecording();
                  }}
                  onMouseLeave={() => {
                    if (isRecording) cancelRecording();
                  }}
                  onTouchStart={(e) => {
                    e.preventDefault();
                    void startRecording();
                  }}
                  onTouchEnd={(e) => {
                    e.preventDefault();
                    stopRecording();
                  }}
                  onTouchCancel={cancelRecording}
                  onContextMenu={(e) => e.preventDefault()}
                  disabled={thread?.isLoading || isMCPLoading || isTranscribing}
                  title={
                    isRecording
                      ? "Отпустите, чтобы распознать"
                      : "Зажмите и диктуйте"
                  }
                  aria-label="Голосовой ввод"
                  aria-pressed={isRecording}
                  className={[
                    "w-9 h-9 p-0 rounded-full flex items-center justify-center transition-colors cursor-pointer outline-hidden disabled:opacity-67 select-none",
                    isRecording
                      ? "bg-red-500/15 text-red-500 animate-pulse"
                      : "text-foreground",
                  ].join(" ")}
                >
                  {isTranscribing ? (
                    <Loader2 className="animate-spin" />
                  ) : (
                    <Mic />
                  )}
                </button>
              )}
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
            </div>
          </div>

          {uploads.length > 0 && (
            <AttachmentsContainer>
              {uploads.map((u: UploadedFile, idx) => (
                <AttachmentBubble
                  key={idx}
                  onClick={() =>
                    u.previewUrl && setEnlargedImage(u.previewUrl!)
                  }
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
              <CloseButton onClick={() => setEnlargedImage(null)}>
                ×
              </CloseButton>
            </Overlay>
          )}
        </div>
      </div>
    </div>
  );
};

export default InputArea;
