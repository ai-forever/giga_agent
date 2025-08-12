import React, { useState, useRef, useEffect } from "react";
import styled from "styled-components";
import { Interrupt } from "@langchain/langgraph-sdk";
import { Check, Paperclip, Send, X } from "lucide-react";
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
import { FileData } from "../interfaces.ts";

const InputContainer = styled.div`
  padding: 16px;
  background-color: #2d2d2d;
  border-top: 1px solid #434343;
  border-radius: 8px;
  box-shadow: 2px 2px 12px 6px #00000024;
  @media print {
    display: none;
  }
`;

const InputRow = styled.div`
  display: flex;
  align-items: flex-end;
  gap: 8px;
`;

const MAX_TEXTAREA_HEIGHT = 200; // макс высота в px

const TextArea = styled.textarea`
  flex: 1;
  min-height: 60px;
  max-height: 200px;
  resize: none;
  font-family:
    -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu,
    Cantarell, "Open Sans", "Helvetica Neue", sans-serif;
  padding: 12px;
  border: none;
  border-radius: 6px;
  background-color: #2d2d2d;
  color: #ffffff;
  font-size: 16px;
  line-height: 1.4;
  overflow-y: auto;
  outline: none;

  &::placeholder {
    color: #999999;
  }
`;

const FileInput = styled.input`
  display: none;
`;

const IconButton = styled.button`
  width: 40px;
  height: 40px;
  padding: 0;
  border: none;
  border-radius: 50%;
  background-color: #2d2d2d;
  color: #ffffff;
  font-size: 20px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background-color 0.2s;

  &:hover {
    background-color: #3b3b3b;
  }

  &:disabled {
    background-color: #2d2d2d;
    cursor: not-allowed;
  }
`;

const SelectedCounter = styled.div<{ $visible: boolean }>`
  margin-top: 6px;
  color: #9e9e9e;
  font-size: 12px;
  position: absolute;
  bottom: 8px;
  left: 75px;
  opacity: ${({ $visible }) => ($visible ? 1 : 0)};
  transform: translateY(${({ $visible }) => ($visible ? 0 : 4)}px);
  transition: ${({ $visible }) =>
    $visible ? "opacity 100ms ease, transform 100ms ease" : "none"};
  pointer-events: none;
`;

// Зелёная кнопка ✔️
const ApproveButton = styled(IconButton)`
  background-color: #28a745;
  color: white;

  &:hover:not(:disabled) {
    background-color: #218838;
  }
`;

// Красная кнопка ✖️
const CancelButton = styled(IconButton)`
  background-color: #dc3545;
  color: white;

  &:hover:not(:disabled) {
    background-color: #c82333;
  }
`;

const SendButton = styled(IconButton)`
  background-color: #2d2d2d;
  &:hover:not(:disabled) {
    background-color: #005bb5;
  }
`;

// Прочие стили для превью и оверлея оставляем без изменений...

interface InputAreaProps {
  onSend: (content: string, attachments?: FileData[]) => void;
  isLoading: boolean;
  interrupt?: Interrupt;
  onContinue: (data: any) => Promise<void>;
}

const InputArea: React.FC<InputAreaProps> = ({
  onSend,
  isLoading,
  interrupt,
  onContinue,
}) => {
  const [message, setMessage] = useState("");
  const [enlargedImage, setEnlargedImage] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const { settings } = useSettings();
  const { uploads, uploadFiles, removeUpload, resetUploads } = useFileUpload();
  const { selected } = useSelectedAttachments();
  const selectedCount = Object.keys(selected).length;

  const isUploading = uploads.some((u) => u.progress < 100 && !u.error);

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
    if (
      interrupt &&
      interrupt.value &&
      // @ts-ignore
      interrupt.value.type === "approve" &&
      settings.autoApprove
    ) {
      handleContinue("approve");
    }
  }, [interrupt, settings.autoApprove]);

  const handleSend = () => {
    if (!message.trim() && uploads.length === 0) return;
    const attachments = uploads.map((u) => u.data).filter(Boolean);
    onSend(message, attachments as any);
    setMessage("");
    resetUploads();
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (!isLoading && !isUploading) {
        if (interrupt) {
          handleContinue(message ? "comment" : "approve");
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

  const handleContinue = (type: "comment" | "approve") => {
    onContinue({ type, message });
    setMessage("");
  };

  return (
    <InputContainer>
      <InputRow>
        <FileInput
          type="file"
          ref={fileInputRef}
          onChange={handleFileChange}
          multiple
          disabled={isLoading}
        />
        <IconButton
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={isLoading}
          title="Добавить вложения"
        >
          <Paperclip />
        </IconButton>

        <TextArea
          placeholder="Спросите что-нибудь…"
          ref={textRef}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={isLoading}
        />
        {interrupt &&
        interrupt.value &&
        // @ts-ignore
        interrupt.value.type === "approve" &&
        !settings.autoApprove ? (
          <>
            <CancelButton
              onClick={() => handleContinue("comment")}
              disabled={isLoading}
              title="Отменить выполнение"
            >
              <X />
            </CancelButton>
            <ApproveButton
              onClick={() => handleContinue("approve")}
              disabled={isLoading}
              title="Подтвердить выполнение"
            >
              <Check />
            </ApproveButton>
          </>
        ) : (
          <SendButton
            type="button"
            onClick={handleSend}
            disabled={isLoading || !message.trim() || isUploading}
            title="Отправить"
          >
            <Send />
          </SendButton>
        )}
      </InputRow>

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

      <SelectedCounter $visible={selectedCount > 0}>
        Выбрано вложений: {selectedCount}
      </SelectedCounter>

      {enlargedImage && (
        <Overlay onClick={() => setEnlargedImage(null)}>
          <EnlargedImage src={enlargedImage} />
          <CloseButton onClick={() => setEnlargedImage(null)}>×</CloseButton>
        </Overlay>
      )}
    </InputContainer>
  );
};

export default InputArea;
