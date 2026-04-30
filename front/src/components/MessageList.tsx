import React from "react";
import Message from "./Message.tsx";
import ToolMessage, { ToolsExecuting } from "./ToolMessage.tsx";
import { Message as Message_ } from "@langchain/langgraph-sdk";
import WellcomeMessage from "./wellcome-message.tsx";
import ThinkingIndicator from "./ThinkingIndicator.tsx";
import type { UseStream } from "@langchain/langgraph-sdk/react";
import { GraphState } from "../interfaces.ts";
import ChatError from "./ChatError.tsx";

interface MessageListProps {
  messages: Message_[];
  thread?: UseStream<GraphState>;
  children?: React.ReactNode;
  notShowWelcomeMessage?: boolean;
  maybeAutoScroll: () => void;
}

const MessageList: React.FC<MessageListProps> = ({
  messages,
  thread,
  children,
  notShowWelcomeMessage,
  maybeAutoScroll,
}) => {
  const lastMessage = messages.at(-1);
  return (
    <div
      className="flex-1 p-5 max-[900px]:p-0"
      style={{ overflowAnchor: "none" }}
    >
      {children}
      {messages.length === 0 && !notShowWelcomeMessage ? (
        <WellcomeMessage />
      ) : null}
      {messages
        .filter(
          (message) =>
            (message.additional_kwargs?.tool_name as string) !== "think",
        )
        .map((message, idx) =>
          message.type === "tool" ? (
            <ToolMessage
              key={idx}
              message={message}
              name={(message.additional_kwargs?.tool_name as string) ?? ""}
            />
          ) : (
            <Message
              key={idx}
              message={message}
              onWrite={maybeAutoScroll}
              thread={thread}
            />
          ),
        )}
      <ChatError thread={thread} />
      {lastMessage && lastMessage.type === "ai" && (
        <ToolsExecuting message={lastMessage} thread={thread} />
      )}

      <ThinkingIndicator messages={messages} thread={thread} />
    </div>
  );
};

export default MessageList;
