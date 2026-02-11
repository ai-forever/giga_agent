import React, { useState } from "react";
import { Message } from "@langchain/langgraph-sdk";
import {
  AttachmentBubble,
  AttachmentsContainer,
  EnlargedImage,
  ImagePreview,
} from "./Attachments.tsx";
import { FileData } from "../interfaces.ts";
import OverlayPortal from "./OverlayPortal.tsx";

interface MessageProps {
  message: Message;
}

const MessageAttachments: React.FC<MessageProps> = ({ message }) => {
  // @ts-ignore
  const uploads = (message.additional_kwargs?.files ?? []) as FileData[];
  const [enlargedImage, setEnlargedImage] = useState<string | null>(null);

  const getPath = (file: FileData): string => {
    const raw = (file as FileData & { sandbox_path?: string }).path;
    if (raw) return raw;
    return (file as FileData & { sandbox_path?: string }).sandbox_path ?? "";
  };

  const getFileUrl = (path: string): string =>
    `/api/files/content/by-path?path=${encodeURIComponent(path)}`;

  const openLink = (url: string) => {
    // @ts-ignore
    window.open(url, "_blank").focus();
  };

  return (
    <>
      {uploads.length > 0 && (
        <AttachmentsContainer
          style={{ justifyContent: "flex-end", marginTop: "0" }}
        >
          {uploads.map((u: FileData, idx) => (
            <AttachmentBubble
              key={idx}
              onClick={() => {
                const path = getPath(u);
                const url = getFileUrl(path);
                if (u.file_type === "image") {
                  setEnlargedImage(url);
                } else {
                  openLink(url);
                }
              }}
            >
              {u.file_type === "image" ? (
                <ImagePreview src={getFileUrl(getPath(u))} />
              ) : (
                <span>{getPath(u).split("/").pop() || getPath(u)}</span>
              )}
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

export default MessageAttachments;
