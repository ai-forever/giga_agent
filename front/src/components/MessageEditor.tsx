import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { FileData, GraphState } from "../interfaces.ts";
import { useFileUpload } from "../hooks/useFileUploads.ts";
import { Paperclip } from "lucide-react";
import {
  AttachmentBubble,
  AttachmentsContainer,
  CircularProgress,
  EnlargedImage,
  ImagePreview,
  ProgressOverlay,
  RemoveButton,
} from "./Attachments.tsx";
import { Checkpoint, HumanMessage, Message } from "@langchain/langgraph-sdk";
import OverlayPortal from "./OverlayPortal.tsx";
import type { UseStream } from "@langchain/langgraph-sdk/react";
import { useSelectedAttachments } from "../hooks/SelectedAttachmentsContext.tsx";
import { useUserInfo } from "@/components/providers/user-info.tsx";
import { useRagContext } from "@/components/rag/providers/RAG.tsx";
import { useSettings } from "@/components/Settings.tsx";

interface MessageEditorProps {
  message: Message;
  onCancel: () => void;
  thread?: UseStream<GraphState>;
}

const MAX_TEXTAREA_HEIGHT = 200;

const MessageEditor: React.FC<MessageEditorProps> = ({
  message,
  onCancel,
  thread,
}) => {
  const textRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [enlargedImage, setEnlargedImage] = useState<string | null>(null);
  const { uploadFiles, setExistingFiles, items, removeItem, getAllFileData } =
    useFileUpload();
  const [messageText, setMessageText] = useState("");
  const { selected } = useSelectedAttachments();
  const { collections, activeCollections } = useRagContext();
  const selectedCount = Object.keys(selected).length;
  const { settings } = useSettings();

  const enabledCollections = useMemo(() => {
    const active = Object.keys(activeCollections).filter(
      (key) => activeCollections[key],
    );
    return collections.filter((collection) => active.includes(collection.uuid));
  }, [activeCollections, collections]);

  const { mcpTools } = useUserInfo();

  const mcpToolsPayload = useMemo(
    () =>
      mcpTools.map((tool) => ({
        name: tool.name,
        description: tool.description,
        inputSchema: tool.inputSchema,
      })),
    [mcpTools],
  );

  useEffect(() => {
    // @ts-ignore
    setMessageText(message.additional_kwargs?.user_input);
    // @ts-ignore
    const initialFiles: FileData[] = message.additional_kwargs?.files ?? [];
    setExistingFiles(initialFiles);
  }, [message, setExistingFiles]);

  // при первом рендере и при очистке
  useEffect(() => {
    autoResize();
  }, [messageText]);

  // автоподгон высоты
  const autoResize = () => {
    const el = textRef.current;
    if (!el) return;
    el.style.height = "auto";
    const newHeight = Math.min(el.scrollHeight, MAX_TEXTAREA_HEIGHT);
    el.style.height = `${newHeight}px`;
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      uploadFiles(Array.from(e.target.files));
      e.target.value = "";
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void handleSendMessage();
    }
  };

  const openLink = (url: string) => {
    // @ts-ignore
    window.open(url, "_blank").focus();
  };

  const handleSendMessage = useCallback(async () => {
    const allFiles = getAllFileData();
    const newMessage = {
      type: "human",
      content: messageText,
      // @ts-ignore
      additional_kwargs: {
        user_input: messageText,
        files: allFiles,
        selected: selected,
      },
    } as HumanMessage;

    const meta = thread?.getMessagesMetadata(message);
    const parentCheckpoint = meta?.firstSeenState?.parent_checkpoint;

    thread?.submit(
      {
        messages: [newMessage],
        mcp_tools: mcpToolsPayload,
        collections: enabledCollections,
        secrets: settings.contextSecrets,
        instructions: settings.contextInstructions,
      },
      {
        optimisticValues(prev: GraphState) {
          const prevMessages = prev.messages ?? [];
          const newMessages = [...prevMessages, newMessage];
          newMessages.forEach((el) => {
            if (el.id === message.id) {
              el.content = messageText;
              // @ts-ignore
              el.additional_kwargs.user_input = messageText;
              // @ts-ignore
              el.additional_kwargs.files = allFiles;
            }
          });
          onCancel();
          return { ...prev, messages: newMessages };
        },
        streamMode: ["messages"],
        onDisconnect: "continue",
        checkpoint: parentCheckpoint,
      },
    );
  }, [
    thread,
    messageText,
    message,
    onCancel,
    getAllFileData,
    selected,
    settings.contextInstructions,
    settings.contextSecrets,
    enabledCollections,
    mcpToolsPayload,
  ]);

  return (
    <>
      <div className="p-4 bg-secondary rounded-lg relative print:hidden">
        <div className="flex items-end gap-2 relative">
          <input
            className="hidden"
            type="file"
            ref={fileInputRef}
            onChange={handleFileChange}
            multiple
          />
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            title="Добавить вложения"
            className="px-2.5 py-2 rounded-md bg-secondary text-foreground text-sm flex items-center justify-center transition-colors hover:bg-accent disabled:bg-secondary disabled:cursor-not-allowed"
          >
            <Paperclip />
          </button>

          <textarea
            placeholder="Спросите что-нибудь…"
            ref={textRef}
            value={messageText}
            onChange={(e) => setMessageText(e.target.value)}
            onKeyDown={handleKeyDown}
            className="flex-1 min-h-[60px] max-h-[200px] resize-none font-sans p-3 rounded-md bg-secondary text-foreground placeholder:text-muted-foreground overflow-y-auto outline-none border-0"
          />
          <button
            type="button"
            title="Отменить"
            onClick={onCancel}
            className="px-3 py-2 rounded-md bg-background text-foreground text-sm cursor-pointer transition-colors hover:bg-accent"
          >
            Отменить
          </button>
          <button
            type="button"
            title="Отправить"
            onClick={handleSendMessage}
            className="px-3 py-2 rounded-md bg-primary text-primary-foreground text-sm cursor-pointer transition-colors hover:opacity-90"
          >
            Отправить
          </button>
        </div>
        <div
          className={[
            "absolute bottom-2 left-20 text-muted-foreground text-xs pointer-events-none transition-opacity duration-100",
            selectedCount > 0
              ? "opacity-100 translate-y-0"
              : "opacity-0 translate-y-1",
          ].join(" ")}
        >
          Выбрано вложений: {selectedCount}
        </div>
      </div>
      {items.length > 0 && (
        <AttachmentsContainer>
          {items.map((it, idx) => (
            <AttachmentBubble
              key={idx}
              onClick={() => {
                if (it.kind === "existing") {
                  const f = it.data!;
                  if (f.file_type === "image")
                    setEnlargedImage("/files/" + f.path);
                  else openLink("/files/" + f.path);
                } else if (it.previewUrl) {
                  setEnlargedImage(it.previewUrl);
                }
              }}
            >
              {it.kind === "existing" ? (
                it.data?.file_type === "image" ? (
                  <ImagePreview src={"/files/" + it.data.path} />
                ) : (
                  <span>
                    {it.name ?? it.data?.path.replace(/^files\//, "")}
                  </span>
                )
              ) : it.previewUrl ? (
                <ImagePreview src={it.previewUrl} />
              ) : (
                <span>{it.name}</span>
              )}

              {it.progress < 100 && (
                <ProgressOverlay>
                  <CircularProgress progress={it.progress}>
                    {it.progress}%
                  </CircularProgress>
                </ProgressOverlay>
              )}

              <RemoveButton
                onClick={(e) => {
                  e.stopPropagation();
                  removeItem(idx);
                }}
              >
                ×
              </RemoveButton>
            </AttachmentBubble>
          ))}
        </AttachmentsContainer>
      )}

      {enlargedImage && (
        <OverlayPortal
          isVisible={!!enlargedImage}
          onClose={() => setEnlargedImage(null)}
        >
          <EnlargedImage src={enlargedImage ?? ""} />
        </OverlayPortal>
      )}
    </>
  );
};

export default React.memo(
  MessageEditor,
  (prev, next) =>
    prev.message === next.message &&
    prev.thread === next.thread &&
    prev.onCancel === next.onCancel,
);
