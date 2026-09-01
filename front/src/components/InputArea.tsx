import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { HumanMessage } from "@langchain/langgraph-sdk";
import * as LucideIcons from "lucide-react";
import {
  Check,
  Files,
  FolderOpen,
  Loader2,
  Mic,
  Paperclip,
  Plus,
  Send,
  Square,
  Wrench,
  X,
} from "lucide-react";
import { useSettings } from "./Settings.tsx";
import { UploadedFile, useFileUpload } from "../hooks/useFileUploads";
import { apiClient, ApiError } from "../lib/api-client.ts";
import {
  API_AGENT_PREFIX,
  BACKEND_STT_ENABLED,
  BROWSER_USE_NAME,
  PROMPT_SUGGESTIONS_ENABLED,
  PROMPT_TEMPLATE_TOPICS,
  STARTER_PROMPT_SUGGESTIONS_ENABLED,
  STARTER_RECOMMENDATIONS_ENABLED,
} from "../config.ts";
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
import {
  appendAskQuestionsResult,
  buildCommentResult,
  findCarrierToolCallId,
} from "./questions/optimistic.ts";
import { appendContextCompactionStarted } from "./context-compaction/optimistic.ts";
import { UseStream } from "@langchain/langgraph-sdk/react";
import { useBranches } from "@/hooks/useBranches";
import { useRagContext } from "@/components/rag/providers/RAG.tsx";
import { getCollectionName } from "@/components/rag/hooks/use-rag";
import { useUserInfo } from "@/components/providers/user-info-context.ts";
import ConnectorsMenu from "@/components/mcp/connectors/connectors-menu.tsx";
import { useSkills } from "@/components/providers/skills.tsx";
import { Switch } from "@/components/ui/switch";
import { useNavigate, useParams } from "react-router-dom";
import { useThreadAutoApprove } from "@/hooks/useThreadAutoApprove";
import { useExperimentalMode } from "@/hooks/useExperimentalMode.ts";
import { useThreadProject } from "@/components/projects/useThreadProject";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ensureNotificationPermission } from "@/lib/notifications";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import ModelPicker from "./ModelPicker";
import TokenUsageIndicator from "./TokenUsageIndicator";
import { useStarterRecommendations } from "@/hooks/useThreadSuggestions";
import {
  getPromptSuggestionTitle,
  type PromptSuggestionScenario,
} from "@/types/prompt-suggestions";

const MAX_TEXTAREA_HEIGHT = 200; // макс высота в px

const newContextCompactionOperationId = () =>
  typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `compact-${Date.now()}`;

const ModuleIcon: React.FC<{ name: string; className?: string }> = ({
  name,
  className,
}) => {
  const Icon = (LucideIcons as unknown as Record<string, React.ElementType>)[
    name
  ];
  const Fallback = LucideIcons.Box;
  const Comp = Icon ?? Fallback;
  return <Comp className={className ?? "size-4"} />;
};

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
  prefillPayload?: {
    suggestion: PromptSuggestionScenario;
    nonce: number;
  } | null;
}

const InputArea: React.FC<InputAreaProps> = ({ thread, prefillPayload }) => {
  const navigate = useNavigate();
  const { threadId } = useParams<{ threadId?: string }>();
  const { autoApprove, setAutoApprove } = useThreadAutoApprove(threadId);
  const { experimentalActive, hideAdvanced } = useExperimentalMode();
  const { project: threadProject } = useThreadProject(threadId);
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
  const [isMCPLoading, setIsMCPLoading] = useState(false);
  const [isStopping, setIsStopping] = useState(false);
  const [deepResearchForced, setDeepResearchForced] = useState(false);
  const [planMode, setPlanMode] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [activeTopicId, setActiveTopicId] = useState<string | null>(null);
  const sttSource = useMemo<SttSource>(() => resolveSttSource(), []);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const recordedChunksRef = useRef<Blob[]>([]);
  const browserRecognitionRef = useRef<BrowserSpeechRecognitionInstance | null>(
    null,
  );
  const browserTranscriptRef = useRef("");
  const cancelRecordingRef = useRef(false);
  const isPlanConfirmed =
    thread?.values?.mode === "normal" && Boolean(thread.values.plan_approved);
  const wasPlanConfirmedRef = useRef(isPlanConfirmed);

  // `present_plan` switches the graph back to normal mode after approval.
  // Keep the local composer toggle in sync so the next user message does not
  // accidentally start another planning turn. React only to a new approval:
  // an approved plan from the chat history must not prevent another plan turn.
  useEffect(() => {
    const wasPlanConfirmed = wasPlanConfirmedRef.current;
    wasPlanConfirmedRef.current = isPlanConfirmed;

    if (planMode && isPlanConfirmed && !wasPlanConfirmed) {
      setPlanMode(false);
    }
  }, [isPlanConfirmed, planMode]);

  const {
    collections,
    activeCollections,
    getCollections,
    initialSearchExecuted,
    initialFetch,
    collectionsLoading,
    activateCollection,
    deactivateCollection,
    deactivateAllCollections,
  } = useRagContext();
  const { settings } = useSettings();
  const {
    mcpTools,
    enabledModules,
    toggleModule,
    setModulesState,
    availableModules,
  } = useUserInfo();
  const {
    skills,
    selectedSkills,
    selectedSkillNames,
    toggleSkill,
    clearSelectedSkills,
    fetchSkills,
    skillsLoading,
  } = useSkills();

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
  const branches = useBranches();
  const isEmptyThread = (thread?.messages?.length ?? 0) === 0;
  const showStarterPromptButtons =
    PROMPT_SUGGESTIONS_ENABLED &&
    STARTER_PROMPT_SUGGESTIONS_ENABLED &&
    isEmptyThread &&
    !thread?.isLoading &&
    !thread?.interrupt;
  const {
    suggestions: recommendationPrompts,
    isLoading: recommendationsLoading,
    loadRecommendations,
  } = useStarterRecommendations(
    PROMPT_SUGGESTIONS_ENABLED && STARTER_RECOMMENDATIONS_ENABLED,
  );
  const activeStarterTopic = useMemo(
    () =>
      PROMPT_TEMPLATE_TOPICS.find((topic) => topic.id === activeTopicId) ??
      null,
    [activeTopicId],
  );
  const isRecommendationsTab = activeTopicId === "recommendations";

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
      // Continue from the branch currently being viewed (head by default),
      // then stream the new run into the head view.
      const baseMessages = branches.isViewingNonHead
        ? branches.activeMessages
        : (thread?.messages ?? []);
      const forkCheckpoint = branches.isViewingNonHead
        ? branches.activeCheckpoint
        : undefined;
      thread?.submit(
        {
          messages: [newMessage],
          collections: enabledCollections,
          mcp_tools: mcpToolsPayload,
        },
        {
          optimisticValues(prev) {
            const prevMessages = prev.messages ?? [];
            const sourceMessages = branches.isViewingNonHead
              ? baseMessages
              : prevMessages;
            const newMessages = [...sourceMessages, newMessage];
            return { ...prev, messages: newMessages };
          },
          checkpoint: forkCheckpoint,
          streamMode: ["messages"],
          onDisconnect: "continue",
          config: {
            configurable: {
              ...(deepResearchForced ? { deep_research_forced: true } : {}),
              plan_mode: planMode,
              ...(selectedSkillNames.length > 0
                ? { selected_skills: selectedSkillNames }
                : {}),
              auto_approve: experimentalActive || autoApprove,
            },
          },
        },
      );
      // Скиллы — одноразовый выбор: сбрасываем чекмарки после отправки.
      if (selectedSkillNames.length > 0) {
        clearSelectedSkills();
      }
    },
    [
      thread,
      branches,
      selected,
      clear,
      mcpToolsPayload,
      enabledCollections,
      deepResearchForced,
      planMode,
      selectedSkillNames,
      clearSelectedSkills,
      autoApprove,
      experimentalActive,
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

  const applySuggestion = useCallback(
    async (
      suggestion: PromptSuggestionScenario,
      options?: { fromStartSuggestions?: boolean; isRecommendation?: boolean },
    ) => {
      const trimmed = suggestion.text.trim();
      if (!trimmed) return;

      const shouldClear =
        options?.fromStartSuggestions && !options?.isRecommendation;

      if (shouldClear) {
        setDeepResearchForced(false);
        clearSelectedSkills();
        deactivateAllCollections();
      }

      if (suggestion.deepResearchForced !== undefined) {
        setDeepResearchForced(suggestion.deepResearchForced);
      }

      if (suggestion.skills) {
        if (!shouldClear) {
          clearSelectedSkills();
        }
        suggestion.skills.forEach((name) => toggleSkill(name, true));
      }

      if (suggestion.ragMode) {
        let availableCollections = collections;
        if (availableCollections.length === 0 && !initialSearchExecuted) {
          await initialFetch();
          availableCollections = await getCollections();
        }
        if (suggestion.ragMode === "all") {
          availableCollections.forEach((collection) =>
            activateCollection(collection.uuid),
          );
        } else {
          availableCollections.forEach((collection) =>
            deactivateCollection(collection.uuid),
          );
        }
      }

      setMessage(trimmed);
      requestAnimationFrame(() => {
        const el = textRef.current;
        if (!el) return;
        el.focus();
        try {
          el.setSelectionRange(trimmed.length, trimmed.length);
        } catch {
          /* selection may fail if unmounted */
        }
      });

      if (shouldClear) {
        const moduleUpdates: Record<string, boolean> = {};
        availableModules.forEach((mod) => {
          moduleUpdates[mod.id] = false;
        });
        if (suggestion.modules) {
          Object.entries(suggestion.modules).forEach(([moduleId, enabled]) => {
            moduleUpdates[moduleId] = enabled;
          });
        }
        void setModulesState(moduleUpdates);
      } else {
        if (suggestion.modules) {
          void Promise.all(
            Object.entries(suggestion.modules).map(([moduleId, enabled]) =>
              toggleModule(moduleId, enabled),
            ),
          );
        }
      }
    },
    [
      activateCollection,
      clearSelectedSkills,
      collections,
      deactivateCollection,
      deactivateAllCollections,
      getCollections,
      initialFetch,
      initialSearchExecuted,
      toggleModule,
      setModulesState,
      availableModules,
      toggleSkill,
    ],
  );

  useEffect(() => {
    if (!prefillPayload?.suggestion) return;
    void applySuggestion(prefillPayload.suggestion);
  }, [applySuggestion, prefillPayload?.nonce, prefillPayload?.suggestion]);

  useEffect(() => {
    // A newly opened chat should start with all starter tabs collapsed.
    setActiveTopicId(null);
  }, [threadId]);

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

  // Свободный ответ на вопросы из поля ввода = comment-resume. В отличие от
  // handleContinue → handleContinueThread (тот оптимистично рисует <decline>),
  // здесь оптимистика строит ту же карточку ask_questions (skipped + comment),
  // что коммитит бэкенд (interrupt_node) — совпадают id и контент, без мелькания.
  const handleQuestionsComment = useCallback(
    (text: string) => {
      const interruptValue = thread?.interrupt?.value;
      const carrierToolCallId = findCarrierToolCallId(thread?.messages ?? []);
      const toolCallId = carrierToolCallId ?? interruptValue?.tool_call_id;
      thread?.submit(undefined, {
        command: { resume: { type: "comment", message: text } },
        optimisticValues: appendAskQuestionsResult(
          toolCallId,
          Boolean(carrierToolCallId),
          buildCommentResult(text),
        ),
        onDisconnect: "continue",
      });
      setMessage("");
    },
    [thread, setMessage],
  );

  // Сохранение частичного AI-ответа живёт в onStop у useStream (Chat.tsx):
  // только там доступны финальные values стрима — любой снимок/реф на этой
  // стороне отстаёт от экрана на последние чанки.
  // Синхронный гард от даблклика: setIsStopping применяется только на
  // следующем рендере, и два быстрых клика могут успеть пройти оба.
  const stopRequestedRef = useRef(false);
  const handleStop = useCallback(() => {
    if (isStopping || stopRequestedRef.current) return;
    stopRequestedRef.current = true;
    setIsStopping(true);
    void thread?.stop();
  }, [isStopping, thread]);

  useEffect(() => {
    if (!thread?.isLoading) {
      setIsStopping(false);
      stopRequestedRef.current = false;
    }
  }, [thread?.isLoading]);

  const handleSend = () => {
    if (message.trim() === "/compact") {
      if (thread?.isLoading || thread?.interrupt) {
        toast.warning("Дождитесь завершения текущего запуска");
        return;
      }
      if (uploads.length > 0 || selectedCount > 0) {
        toast.warning("Уберите вложения перед командой /compact");
        return;
      }
      if (!thread || (thread.messages?.length ?? 0) === 0) {
        toast.info("Недостаточно истории для сокращения");
        return;
      }
      const forkCheckpoint = branches.isViewingNonHead
        ? branches.activeCheckpoint
        : undefined;
      const baseMessages = branches.isViewingNonHead
        ? branches.activeMessages
        : (thread.messages ?? []);
      const operationId = newContextCompactionOperationId();
      thread.submit({} as any, {
        optimisticValues: appendContextCompactionStarted(
          operationId,
          baseMessages,
        ),
        checkpoint: forkCheckpoint,
        streamMode: ["messages"],
        onDisconnect: "continue",
        config: {
          configurable: {
            context_compaction_only: true,
            context_compaction_operation_id: operationId,
          },
        },
      });
      setMessage("");
      toast.info("Сокращаю контекст…");
      return;
    }
    // При активном interrupt поле ввода отвечает НА НЕГО, а не шлёт новый ран
    // (та же логика, что в handleKeyDown): вопросы → свободный comment, прочее →
    // comment/approve.
    if (thread?.interrupt) {
      if (thread.interrupt.value?.type === "questions") {
        if (message.trim()) handleQuestionsComment(message);
      } else {
        void handleContinue(message.trim() ? "comment" : "approve");
      }
      return;
    }
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

  // Plan mode персистит между отправками — сбрасывается только повторным кликом.
  const togglePlanMode = useCallback(() => {
    setPlanMode((prev) => !prev);
  }, []);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (isMobileDevice) return;

    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (!thread?.isLoading && !isUploading) {
        if (thread?.interrupt) {
          // План подтверждается кнопками карточки, не Enter в композере.
          if (thread.interrupt.value?.type !== "plan_approval") {
            if (thread.interrupt.value?.type === "questions") {
              if (message.trim()) handleQuestionsComment(message);
            } else {
              void handleContinue(message ? "comment" : "approve");
            }
          }
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

  const showStopButton =
    !!thread?.isLoading && !thread?.interrupt && !isMCPLoading;

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
      ) : showStopButton ? (
        <button
          type="button"
          onClick={handleStop}
          disabled={isStopping}
          title="Остановить"
          aria-label="Остановить"
          className="w-7 h-7 p-0 rounded-full bg-foreground text-background flex items-center justify-center transition-colors cursor-pointer outline-hidden hover:bg-foreground/85 disabled:opacity-67"
        >
          <Square className="fill-current size-3" />
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

  const enabledCollectionCount = enabledCollections.length;

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
      <div className="relative p-4 pb-3 bg-card dark:bg-input border-border rounded-lg print:hidden border-1 border-highlight max-w-[880px] mx-auto overflow-hidden">
        <div className="relative">
          <input
            className="hidden"
            type="file"
            ref={fileInputRef}
            onChange={handleFileChange}
            multiple
            disabled={thread?.isLoading || isMCPLoading}
          />
          <div className={"flex flex-col"}>
            <textarea
              data-onboarding="chat-input"
              placeholder={
                thread?.interrupt?.value?.type === "questions"
                  ? "Ответьте на вопросы выше или введите комментарий…"
                  : thread?.interrupt
                    ? "Принять / Отменить с комментарием…"
                    : "Введите вашу задачу…"
              }
              ref={textRef}
              rows={1}
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              onKeyDown={handleKeyDown}
              onPaste={handlePaste}
              disabled={thread?.isLoading || isMCPLoading}
              className="w-full min-h-[60px] max-h-[200px] resize-none font-sans p-2 rounded-md text-foreground placeholder:text-muted-foreground overflow-y-auto outline-none border-0 disabled:opacity-60 max-[900px]:min-h-[60px] max-[900px]:h-[60px]"
            />
            <div className={"flex"}>
              <div className="flex items-center gap-1 flex-1 min-w-0">
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <button
                      data-onboarding="gear-menu-btn"
                      type="button"
                      disabled={thread?.isLoading || isMCPLoading}
                      title="Добавить"
                      className="w-7 h-7 p-0 rounded-full text-foreground flex items-center justify-center transition-colors cursor-pointer outline-hidden disabled:opacity-67"
                    >
                      <Plus />
                    </button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent
                    className="input-dropdown"
                    align="start"
                    sideOffset={3}
                  >
                    <DropdownMenuItem
                      onSelect={() => fileInputRef.current?.click()}
                    >
                      <Paperclip className={"size-5"} />
                      <span>Прикрепить файл</span>
                    </DropdownMenuItem>
                    <DropdownMenuSub
                      onOpenChange={(open) => {
                        if (open) {
                          if (!initialSearchExecuted) void initialFetch();
                          if (collections.length === 0) void getCollections();
                        }
                      }}
                    >
                      <DropdownMenuSubTrigger className="gap-2">
                        <Files className="size-5" />
                        <span>Документы</span>
                      </DropdownMenuSubTrigger>
                      <DropdownMenuSubContent className="min-w-[250px] max-h-[50vh] overflow-y-auto p-2 space-y-1">
                        {collectionsLoading && (
                          <div className="px-2 py-1.5 text-sm text-muted-foreground">
                            Загрузка…
                          </div>
                        )}
                        {!collectionsLoading && collections.length === 0 && (
                          <div className="px-2 py-1.5 text-sm text-muted-foreground">
                            Папки не найдены
                          </div>
                        )}
                        {!collectionsLoading &&
                          collections.map((c) => {
                            const isOn = Boolean(activeCollections[c.uuid]);
                            return (
                              <button
                                key={c.uuid}
                                type="button"
                                onClick={() => {
                                  if (isOn) deactivateCollection(c.uuid);
                                  else activateCollection(c.uuid);
                                }}
                                className="w-full flex items-center justify-between gap-3 rounded-md px-2 py-1.5 text-left hover:bg-accent cursor-pointer"
                              >
                                <span className="text-sm truncate">
                                  {getCollectionName(c.name)}
                                </span>
                                <div className="size-4 shrink-0 flex items-center justify-center">
                                  {isOn && (
                                    <Check className="size-4 text-primary" />
                                  )}
                                </div>
                              </button>
                            );
                          })}
                      </DropdownMenuSubContent>
                    </DropdownMenuSub>
                    <DropdownMenuSub
                      onOpenChange={(open) => {
                        if (open && skills.length === 0) void fetchSkills();
                      }}
                    >
                      <DropdownMenuSubTrigger className="gap-2">
                        <LucideIcons.Sparkles className="size-5" />
                        <span>Скиллы</span>
                      </DropdownMenuSubTrigger>
                      <DropdownMenuSubContent className="min-w-[250px] max-h-[50vh] overflow-y-auto p-2 space-y-1">
                        {skillsLoading && (
                          <div className="px-2 py-1.5 text-sm text-muted-foreground">
                            Загрузка…
                          </div>
                        )}
                        {!skillsLoading && skills.length === 0 && (
                          <div className="px-2 py-1.5 text-sm text-muted-foreground">
                            Нет доступных скиллов
                          </div>
                        )}
                        {!skillsLoading &&
                          skills.map((s) => {
                            const isOn = selectedSkills[s.name] === true;
                            return (
                              <button
                                key={s.id}
                                type="button"
                                onClick={() => toggleSkill(s.name, !isOn)}
                                className="w-full flex items-center justify-between gap-3 rounded-md px-2 py-1.5 text-left hover:bg-accent cursor-pointer"
                              >
                                <div className="min-w-0">
                                  <div className="text-sm font-medium truncate">
                                    {s.name}
                                  </div>
                                  {s.description && (
                                    <div className="text-xs text-muted-foreground truncate">
                                      {s.description.length > 50
                                        ? `${s.description.slice(0, 50)}...`
                                        : s.description}
                                    </div>
                                  )}
                                </div>
                                <div className="size-4 shrink-0 flex items-center justify-center">
                                  {isOn && (
                                    <Check className="size-4 text-primary" />
                                  )}
                                </div>
                              </button>
                            );
                          })}
                      </DropdownMenuSubContent>
                    </DropdownMenuSub>
                    <DropdownMenuItem
                      onSelect={(e) => {
                        e.preventDefault();
                        void toggleDeepResearchForced();
                      }}
                      className="gap-2"
                    >
                      <LucideIcons.ScanSearch className="size-5" />
                      <span className="flex-1">Исследование</span>
                      <div className="size-4 shrink-0 flex items-center justify-center">
                        {deepResearchForced && (
                          <Check className="size-4 text-primary" />
                        )}
                      </div>
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      onSelect={(e) => {
                        e.preventDefault();
                        togglePlanMode();
                      }}
                      className="gap-2"
                    >
                      <LucideIcons.ListChecks className="size-5" />
                      <span className="flex-1">Режим планирования</span>
                      <div className="size-4 shrink-0 flex items-center justify-center">
                        {planMode && <Check className="size-4 text-primary" />}
                      </div>
                    </DropdownMenuItem>
                    <ConnectorsMenu />
                    <DropdownMenuSub>
                      <DropdownMenuSubTrigger className="gap-2">
                        <Wrench className="size-5" />
                        <span>Модули</span>
                      </DropdownMenuSubTrigger>
                      <DropdownMenuSubContent className="min-w-[250px] max-h-[50vh] overflow-y-auto p-2 space-y-1">
                        {availableModules.length === 0 && (
                          <div className="px-2 py-3 text-xs text-muted-foreground text-center">
                            Нет доступных модулей
                          </div>
                        )}
                        <div>
                          {availableModules.map((mod) => (
                            <div
                              key={mod.id}
                              className="flex items-center justify-between gap-3 rounded-md px-2 py-1.5 hover:bg-accent"
                            >
                              <div className="flex items-center gap-2 min-w-0">
                                <ModuleIcon
                                  name={mod.icon}
                                  className="size-5 shrink-0 text-muted-foreground"
                                />
                                <div className="min-w-0">
                                  <div className="text-sm font-medium truncate">
                                    {mod.label}
                                  </div>
                                  <div className="text-xs text-muted-foreground">
                                    {mod.description}
                                  </div>
                                </div>
                              </div>
                              <Switch
                                checked={enabledModules[mod.id] !== false}
                                onCheckedChange={(checked) =>
                                  toggleModule(mod.id, Boolean(checked))
                                }
                              />
                            </div>
                          ))}
                        </div>
                      </DropdownMenuSubContent>
                    </DropdownMenuSub>
                  </DropdownMenuContent>
                </DropdownMenu>
                {threadProject && (
                  <button
                    type="button"
                    onClick={() => navigate(`/projects/${threadProject.id}`)}
                    className="inline-flex items-center gap-1 h-7 px-2 rounded-full text-xs text-muted-foreground hover:text-foreground hover:bg-muted transition-colors min-w-0 max-w-[180px]"
                    title="Открыть проект"
                  >
                    <FolderOpen className="h-3.5 w-3.5 shrink-0" />
                    <span className="truncate">{threadProject.name}</span>
                  </button>
                )}
                {enabledCollectionCount > 0 && (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <div className="relative w-9 h-9 p-0 rounded-full text-foreground flex items-center justify-center mr-1">
                        <Files className="size-5" />
                        <span className="absolute -top-1 -right-1 bg-primary text-primary-foreground text-[10px] font-bold rounded-full min-w-[15px] h-[15px] flex items-center justify-center px-1">
                          {enabledCollectionCount}
                        </span>
                      </div>
                    </TooltipTrigger>
                    <TooltipContent side="top" align="start">
                      <div className="text-xs space-y-0.5">
                        {enabledCollections.map((c) => (
                          <div key={c.uuid}>{c.name}</div>
                        ))}
                      </div>
                    </TooltipContent>
                  </Tooltip>
                )}
                {selectedSkillNames.length > 0 && (
                  <div className="flex items-center gap-1 flex-wrap">
                    {selectedSkillNames.map((name) => (
                      <button
                        key={name}
                        type="button"
                        onClick={() => toggleSkill(name, false)}
                        title={`Убрать скилл ${name}`}
                        aria-label={`Убрать скилл ${name}`}
                        className="group inline-flex items-center gap-1 rounded-full border border-primary/20 bg-muted/10 px-2 py-1 text-xs font-medium text-primary shadow-[0_1px_2px_rgba(0,0,0,0.04)] transition-colors duration-150 cursor-pointer hover:bg-muted/20 hover:border-primary/30 dark:bg-primary/20 dark:border-primary/30 dark:hover:bg-primary/30 dark:hover:border-primary/40"
                      >
                        <Wrench className="size-3 group-hover:hidden" />
                        <X className="size-3 hidden group-hover:block" />
                        <span className="truncate max-w-40">{name}</span>
                      </button>
                    ))}
                  </div>
                )}
                {deepResearchForced && (
                  <button
                    type="button"
                    onClick={() => setDeepResearchForced(false)}
                    title="Убрать исследование"
                    aria-label="Убрать исследование"
                    className="group inline-flex items-center gap-1 rounded-full border border-primary/20 bg-muted/10 px-2 py-1 text-xs font-medium text-primary shadow-[0_1px_2px_rgba(0,0,0,0.04)] transition-colors duration-150 cursor-pointer hover:bg-muted/20 hover:border-primary/30 dark:bg-primary/20 dark:border-primary/30 dark:hover:bg-primary/30 dark:hover:border-primary/40"
                  >
                    <LucideIcons.ScanSearch className="size-3 group-hover:hidden" />
                    <X className="size-3 hidden group-hover:block" />
                    <span className="truncate max-w-40">
                      Глубокое исследование
                    </span>
                  </button>
                )}
                {planMode && (
                  <button
                    type="button"
                    onClick={() => setPlanMode(false)}
                    title="Выключить режим планирования"
                    aria-label="Выключить режим планирования"
                    className="group inline-flex items-center gap-1 rounded-full border border-primary/20 bg-muted/10 px-2 py-1 text-xs font-medium text-primary shadow-[0_1px_2px_rgba(0,0,0,0.04)] transition-colors duration-150 cursor-pointer hover:bg-muted/20 hover:border-primary/30 dark:bg-primary/20 dark:border-primary/30 dark:hover:bg-primary/30 dark:hover:border-primary/40"
                  >
                    <LucideIcons.ListChecks className="size-3 group-hover:hidden" />
                    <X className="size-3 hidden group-hover:block" />
                    <span className="truncate max-w-40">
                      Режим планирования
                    </span>
                  </button>
                )}
              </div>
              <div className="self-end mb-1 shrink-0 flex items-center gap-1">
                <TokenUsageIndicator messages={thread?.messages ?? []} />
                {!hideAdvanced && (
                  <ModelPicker disabled={thread?.isLoading || isMCPLoading} />
                )}
              </div>
              <div>{renderInputActions()}</div>
            </div>
            <div>
              <div className={"flex align-middle"}>
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
              </div>
            </div>
          </div>
          {/* В экспериментальном режиме автономность всегда включена (граф
              форсит auto_approve на сервере), поэтому у не-админов тумблер
              скрываем. */}
          {!hideAdvanced && (
            <label
              data-onboarding="autonomy-switch"
              className="absolute top-0 right-0 flex items-center gap-2 select-none text-[11px] text-muted-foreground leading-none"
            >
              <span>Автономность</span>
              <Switch
                checked={autoApprove}
                onCheckedChange={(checked) => setAutoApprove(checked)}
              />
            </label>
          )}
        </div>

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
      {showStarterPromptButtons && (
        <div className="max-w-[880px] mx-auto mt-2 mb-1 print:hidden">
          <div className="flex flex-wrap items-center gap-2">
            {STARTER_RECOMMENDATIONS_ENABLED && (
              <button
                type="button"
                onClick={() => {
                  setActiveTopicId("recommendations");
                  if (recommendationPrompts.length === 0) {
                    void loadRecommendations(false);
                  }
                }}
                className={[
                  "inline-flex items-center gap-1 rounded-full border px-3 py-1.5 text-xs transition-colors cursor-pointer",
                  isRecommendationsTab
                    ? "border-primary/30 bg-primary/10 text-primary"
                    : "border-border bg-muted/40 text-foreground hover:bg-muted",
                ].join(" ")}
              >
                <LucideIcons.Sparkle className="size-3.5 shrink-0" />
                Рекомендации
              </button>
            )}
            {PROMPT_TEMPLATE_TOPICS.map((topic) => (
              <button
                key={topic.id}
                type="button"
                onClick={() => setActiveTopicId(topic.id)}
                className={[
                  "inline-flex items-center rounded-full border px-3 py-1.5 text-xs transition-colors cursor-pointer",
                  activeTopicId === topic.id
                    ? "border-primary/30 bg-primary/10 text-primary"
                    : "border-border bg-muted/40 text-foreground hover:bg-muted",
                ].join(" ")}
              >
                {topic.label}
              </button>
            ))}
          </div>

          {(activeStarterTopic || isRecommendationsTab) && (
            <div className="mt-2 rounded-lg border border-border bg-card p-2">
              {activeStarterTopic &&
                activeStarterTopic.prompts.map((prompt, idx) => (
                  <button
                    key={`${prompt.text}-${idx}`}
                    type="button"
                    onClick={() =>
                      void applySuggestion(prompt, {
                        fromStartSuggestions: true,
                        isRecommendation: false,
                      })
                    }
                    className="w-full rounded-md px-2 py-2 text-left text-sm transition-colors hover:bg-muted cursor-pointer"
                  >
                    {getPromptSuggestionTitle(prompt)}
                  </button>
                ))}

              {isRecommendationsTab &&
                (recommendationsLoading ? (
                  <div className="px-2 py-1.5 space-y-2">
                    <div className="h-8 w-full rounded-md bg-muted animate-pulse" />
                    <div className="h-8 w-full rounded-md bg-muted animate-pulse" />
                    <div className="h-8 w-full rounded-md bg-muted animate-pulse" />
                  </div>
                ) : recommendationPrompts.length > 0 ? (
                  recommendationPrompts.map((prompt, idx) => (
                    <button
                      key={`${prompt.text}-${idx}`}
                      type="button"
                      onClick={() =>
                        void applySuggestion(
                          {
                            text: prompt.text,
                            title: prompt.title,
                          },
                          {
                            fromStartSuggestions: true,
                            isRecommendation: true,
                          },
                        )
                      }
                      className="w-full rounded-md px-2 py-2 text-left text-sm transition-colors hover:bg-muted cursor-pointer"
                    >
                      {getPromptSuggestionTitle(prompt)}
                    </button>
                  ))
                ) : (
                  <button
                    type="button"
                    onClick={() => void loadRecommendations(true)}
                    className="w-full rounded-md px-2 py-2 text-left text-sm text-muted-foreground transition-colors hover:bg-muted cursor-pointer"
                  >
                    Обновить рекомендации
                  </button>
                ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default InputArea;
