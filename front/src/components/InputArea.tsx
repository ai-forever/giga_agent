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
  ScanSearch,
  Mic,
  Loader2,
  Check,
  X,
} from "lucide-react";
import { useSettings } from "./Settings.tsx";
import { useFileUpload, UploadedFile } from "../hooks/useFileUploads";
import { apiClient, ApiError } from "../lib/api-client.ts";
import { API_AGENT_PREFIX, BACKEND_STT_ENABLED } from "../config.ts";
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
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ensureNotificationPermission } from "@/lib/notifications";
import ModelPicker from "./ModelPicker";

const MAX_TEXTAREA_HEIGHT = 200; // макс высота в px

const getInitialIsMobileDevice = () => {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia("(pointer: coarse)").matches;
};

type BrowserSpeechRecognitionInstance = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((event: Event) => void) | null;
  onerror: ((event: Event) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
};
type BrowserSpeechRecognitionCtor = new () => BrowserSpeechRecognitionInstance;

const BrowserSpeechRecognitionClass: BrowserSpeechRecognitionCtor | undefined =
  typeof window !== "undefined"
    ? (((window as unknown as Record<string, unknown>).SpeechRecognition as
        | BrowserSpeechRecognitionCtor
        | undefined) ??
      ((window as unknown as Record<string, unknown>)
        .webkitSpeechRecognition as BrowserSpeechRecognitionCtor | undefined))
    : undefined;

type SttSource = "backend" | "browser" | null;

const resolveSttSource = (): SttSource => {
  if (typeof window === "undefined") return null;
  if (
    BACKEND_STT_ENABLED &&
    typeof window.MediaRecorder !== "undefined" &&
    !!navigator.mediaDevices?.getUserMedia
  ) {
    return "backend";
  }
  if (BrowserSpeechRecognitionClass) return "browser";
  return null;
};

// Прочие стили для превью и оверлея оставляем без изменений...

interface InputAreaProps {
  thread?: UseStream<GraphState, GraphTemplate>;
}

const InputArea: React.FC<InputAreaProps> = ({ thread }) => {
  const navigate = useNavigate();
  const [message, setMessage] = useState("");
  const [isMobileDevice, setIsMobileDevice] = useState(
    getInitialIsMobileDevice,
  );
  const [enlargedImage, setEnlargedImage] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const dragCounterRef = useRef(0);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const { uploads, uploadFiles, removeUpload, resetUploads } = useFileUpload();
  const { selected, clear } = useSelectedAttachments();
  const autoApproveLockRef = useRef<unknown>(null);
  const [isMCPLoading, setIsMCPLoading] = useState(false);
  const [deepResearchForced, setDeepResearchForced] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const sttSource = useMemo<SttSource>(() => resolveSttSource(), []);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const recordedChunksRef = useRef<Blob[]>([]);
  const browserRecognitionRef = useRef<BrowserSpeechRecognitionInstance | null>(
    null,
  );
  const browserTranscriptRef = useRef("");
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
          config: deepResearchForced
            ? { configurable: { deep_research_forced: true } }
            : undefined,
        },
      );
    },
    [
      thread,
      selected,
      clear,
      mcpToolsPayload,
      enabledCollections,
      user,
      deepResearchForced,
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
    const computedBefore = window.getComputedStyle(el);
    el.style.height = "auto";
    const scrollHeightAfterAuto = el.scrollHeight;
    const baseHeight = Number.parseFloat(computedBefore.minHeight);
    const hasText = el.value.length > 0;
    const newHeight = hasText
      ? Math.min(scrollHeightAfterAuto, MAX_TEXTAREA_HEIGHT)
      : Number.isFinite(baseHeight) && baseHeight > 0
        ? baseHeight
        : Math.min(scrollHeightAfterAuto, MAX_TEXTAREA_HEIGHT);
    el.style.height = `${newHeight}px`;
  };

  // при первом рендере и при очистке
  useEffect(() => {
    autoResize();
  }, [message, isMobileDevice]);

  useEffect(() => {
    if (!window.matchMedia) return;

    const media = window.matchMedia("(pointer: coarse)");
    const updateIsMobileDevice = () => setIsMobileDevice(media.matches);

    updateIsMobileDevice();
    media.addEventListener("change", updateIsMobileDevice);

    return () => media.removeEventListener("change", updateIsMobileDevice);
  }, []);

  useEffect(() => {
    return () => {
      mediaStreamRef.current?.getTracks().forEach((t) => t.stop());
      mediaStreamRef.current = null;
      mediaRecorderRef.current = null;
      try {
        browserRecognitionRef.current?.abort();
      } catch {
        /* instance may be already stopped */
      }
      browserRecognitionRef.current = null;
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

  const teardownBackendRecording = useCallback(() => {
    mediaStreamRef.current?.getTracks().forEach((t) => t.stop());
    mediaStreamRef.current = null;
    mediaRecorderRef.current = null;
    recordedChunksRef.current = [];
  }, []);

  const finishBackendRecording = useCallback(
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
      teardownBackendRecording();
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
    [teardownBackendRecording, insertAtCursor],
  );

  const startRecording = useCallback(async () => {
    if (isRecording || isTranscribing) return;
    if (thread?.isLoading || isMCPLoading) return;
    if (!sttSource) return;
    cancelRecordingRef.current = false;

    if (sttSource === "backend") {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: true,
        });
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
        rec.start();
        setIsRecording(true);
      } catch {
        teardownBackendRecording();
        setIsRecording(false);
      }
      return;
    }

    // Browser Web Speech API path
    const Ctor = BrowserSpeechRecognitionClass;
    if (!Ctor) return;
    try {
      const rec = new Ctor();
      rec.lang = navigator.language || "ru-RU";
      rec.continuous = true;
      rec.interimResults = false;
      browserTranscriptRef.current = "";
      rec.onresult = (event: Event) => {
        const anyEvent = event as unknown as {
          resultIndex: number;
          results: ArrayLike<
            ArrayLike<{ transcript: string }> & { isFinal: boolean }
          >;
        };
        for (let i = anyEvent.resultIndex; i < anyEvent.results.length; i++) {
          const result = anyEvent.results[i];
          if (result.isFinal) {
            browserTranscriptRef.current += result[0].transcript;
          }
        }
      };
      rec.onerror = () => {
        cancelRecordingRef.current = true;
      };
      rec.onend = () => {
        const wasCancelled = cancelRecordingRef.current;
        const transcript = browserTranscriptRef.current.trim();
        browserRecognitionRef.current = null;
        cancelRecordingRef.current = false;
        browserTranscriptRef.current = "";
        setIsRecording(false);
        if (!wasCancelled && transcript) insertAtCursor(transcript);
      };
      browserRecognitionRef.current = rec;
      rec.start();
      setIsRecording(true);
    } catch {
      browserRecognitionRef.current = null;
      setIsRecording(false);
    }
  }, [
    isRecording,
    isTranscribing,
    sttSource,
    thread?.isLoading,
    isMCPLoading,
    teardownBackendRecording,
    insertAtCursor,
  ]);

  const acceptRecording = useCallback(() => {
    if (!isRecording) return;
    if (sttSource === "backend") {
      cancelRecordingRef.current = false;
      void finishBackendRecording(false);
      return;
    }
    cancelRecordingRef.current = false;
    try {
      browserRecognitionRef.current?.stop();
    } catch {
      /* stop may throw if already ended */
    }
  }, [isRecording, sttSource, finishBackendRecording]);

  const cancelRecording = useCallback(() => {
    if (!isRecording) return;
    if (sttSource === "backend") {
      cancelRecordingRef.current = true;
      void finishBackendRecording(true);
      return;
    }
    cancelRecordingRef.current = true;
    try {
      browserRecognitionRef.current?.abort();
    } catch {
      /* abort may throw if already ended */
    }
  }, [isRecording, sttSource, finishBackendRecording]);

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
    setDeepResearchForced(false);
  };

  const toggleDeepResearchForced = useCallback(async () => {
    setDeepResearchForced((prev) => {
      const next = !prev;
      if (next) void ensureNotificationPermission();
      return next;
    });
  }, []);

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

  useEffect(() => {
    const hasFiles = (e: DragEvent) =>
      Array.from(e.dataTransfer?.types ?? []).includes("Files");

    const onDragEnter = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      dragCounterRef.current += 1;
      if (!isBusy) setIsDragging(true);
    };
    const onDragOver = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      if (e.dataTransfer) e.dataTransfer.dropEffect = isBusy ? "none" : "copy";
    };
    const onDragLeave = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      dragCounterRef.current = Math.max(0, dragCounterRef.current - 1);
      if (dragCounterRef.current === 0) setIsDragging(false);
    };
    const onDrop = (e: DragEvent) => {
      e.preventDefault();
      dragCounterRef.current = 0;
      setIsDragging(false);
      if (isBusy) return;
      const files = Array.from(e.dataTransfer?.files ?? []);
      if (files.length > 0) uploadFiles(files);
    };

    window.addEventListener("dragenter", onDragEnter);
    window.addEventListener("dragover", onDragOver);
    window.addEventListener("dragleave", onDragLeave);
    window.addEventListener("drop", onDrop);
    return () => {
      window.removeEventListener("dragenter", onDragEnter);
      window.removeEventListener("dragover", onDragOver);
      window.removeEventListener("dragleave", onDragLeave);
      window.removeEventListener("drop", onDrop);
    };
  }, [uploadFiles, isBusy]);

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

  const showMicButton =
    sttSource !== null &&
    !isRecording &&
    !isTranscribing &&
    !isBusy &&
    !message.trim() &&
    uploads.length === 0 &&
    !thread?.interrupt;

  const renderInputActions = (className?: string) => (
    <div
      className={
        className ??
        (isRecording
          ? "flex items-center gap-2"
          : "flex flex-col items-end gap-1")
      }
    >
      {isRecording ? (
        <>
          <button
            type="button"
            onClick={cancelRecording}
            title="Отменить запись"
            aria-label="Отменить запись"
            className="w-9 h-9 p-0 rounded-full text-destructive hover:bg-destructive/10 flex items-center justify-center transition-colors cursor-pointer outline-hidden"
          >
            <X />
          </button>
          <button
            type="button"
            onClick={acceptRecording}
            title="Готово"
            aria-label="Готово"
            className="w-9 h-9 p-0 rounded-full bg-red-500/15 text-red-500 animate-pulse flex items-center justify-center transition-colors cursor-pointer outline-hidden"
          >
            <Check />
          </button>
        </>
      ) : isTranscribing ? (
        <button
          type="button"
          disabled
          title="Распознавание…"
          aria-label="Распознавание"
          className="w-9 h-9 p-0 rounded-full text-foreground flex items-center justify-center outline-hidden"
        >
          <Loader2 className="animate-spin" />
        </button>
      ) : showMicButton ? (
        <button
          type="button"
          onClick={() => void startRecording()}
          title="Голосовой ввод"
          aria-label="Голосовой ввод"
          className="w-9 h-9 p-0 rounded-full text-foreground flex items-center justify-center transition-colors cursor-pointer outline-hidden"
        >
          <Mic />
        </button>
      ) : (
        <button
          type="button"
          onClick={handleSend}
          disabled={
            thread?.isLoading || isMCPLoading || !message.trim() || isUploading
          }
          title="Отправить"
          className="w-9 h-9 p-0 rounded-full text-foreground flex items-center justify-center transition-colors cursor-pointer outline-hidden disabled:opacity-67"
        >
          <Send />
        </button>
      )}
    </div>
  );

  const renderAttachmentButton = (className?: string) => (
    <button
      data-onboarding="attachments-btn"
      type="button"
      onClick={() => fileInputRef.current?.click()}
      disabled={thread?.isLoading || isMCPLoading}
      title="Добавить вложения"
      className={
        className ??
        "w-9 h-9 p-0 rounded-full text-foreground flex items-center justify-center transition-colors cursor-pointer outline-hidden disabled:opacity-67"
      }
    >
      <Paperclip />
    </button>
  );

  return (
    <div className="bg-card w-full sticky bottom-0 p-5 pt-0 max-[900px]:p-0 z-9">
      {isDragging && (
        <div
          className={[
            "fixed inset-0 z-[100] flex items-center justify-center bg-background/70 backdrop-blur-sm pointer-events-none print:hidden animate-in fade-in duration-150",
            settings.sideBarOpen ? "min-[900px]:left-[200px]" : "",
          ].join(" ")}
        >
          <div className="m-6 flex flex-col items-center gap-4 px-8 py-10 text-foreground text-base font-medium">
            <Files className="size-14 text-foreground/90" />
            Отпустите, чтобы прикрепить файлы
          </div>
        </div>
      )}
      <div className="relative p-4 bg-card dark:bg-input border-border rounded-lg print:hidden border-1 border-highlight max-w-[900px] mx-auto overflow-hidden">
        <div className="flex items-end gap-2 relative">
          <input
            className="hidden"
            type="file"
            ref={fileInputRef}
            onChange={handleFileChange}
            multiple
            disabled={thread?.isLoading || isMCPLoading}
          />
          <div className="flex flex-col items-center gap-1 self-start">
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
                <DropdownMenuCheckboxItem
                  checked={deepResearchForced}
                  onCheckedChange={() => void toggleDeepResearchForced()}
                  onSelect={(e) => e.preventDefault()}
                >
                  <ScanSearch className={"size-5"} />
                  <span>Глубокое исследование</span>
                </DropdownMenuCheckboxItem>
                <DropdownMenuSeparator />
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
            <div className="max-[900px]:hidden">{renderAttachmentButton()}</div>
          </div>

          <textarea
            data-onboarding="chat-input"
            placeholder={
              thread?.interrupt
                ? "Принять / Отменить с комментарием…"
                : "Введите вашу задачу…"
            }
            ref={textRef}
            rows={isMobileDevice ? 1 : 2}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={handleKeyDown}
            onPaste={handlePaste}
            disabled={thread?.isLoading || isMCPLoading}
            className="flex-1 min-h-[76px] max-h-[200px] resize-none font-sans p-3 rounded-md text-foreground placeholder:text-muted-foreground overflow-y-auto outline-none border-0 disabled:opacity-60 max-[900px]:min-h-[60px] max-[900px]:h-[60px]"
          />
          <div className="self-end mb-1 shrink-0 max-[900px]:hidden">
            <ModelPicker disabled={thread?.isLoading || isMCPLoading} />
          </div>
          <div className="max-[900px]:hidden">{renderInputActions()}</div>
          <label
            data-onboarding="autonomy-switch"
            className="absolute top-0 right-0 flex items-center gap-2 select-none text-[11px] text-muted-foreground leading-none"
          >
            <span>Автономность</span>
            <Switch
              checked={settings.autoApprove ?? false}
              onCheckedChange={(checked) =>
                setSettings((prev) => ({ ...prev, autoApprove: checked }))
              }
            />
          </label>
        </div>
        <div className="hidden max-[900px]:flex items-center justify-between gap-2">
          {renderAttachmentButton()}
          <div className="flex items-center gap-2 shrink-0">
            <ModelPicker disabled={thread?.isLoading || isMCPLoading} />
            {renderInputActions("flex items-center gap-2")}
          </div>
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
          <Overlay
            onClick={() => setEnlargedImage(null)}
            style={{ left: settings.sideBarOpen ? "265px" : "0" }}
          >
            <EnlargedImage src={enlargedImage} />
            <CloseButton onClick={() => setEnlargedImage(null)}>×</CloseButton>
          </Overlay>
        )}
      </div>
    </div>
  );
};

export default InputArea;
