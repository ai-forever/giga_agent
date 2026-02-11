import React, { useEffect } from "react";
import MessageList from "./MessageList";
import InputArea from "./InputArea";
import { useStableMessages } from "../hooks/useStableMessages";
import { GraphState } from "../interfaces";
import { useNavigate, useParams } from "react-router-dom";
import { uiMessageReducer } from "@langchain/langgraph-sdk/react-ui";
import { SelectedAttachmentsProvider } from "../hooks/SelectedAttachmentsContext.tsx";
import { useStream, UseStream } from "@langchain/langgraph-sdk/react";
import { useAuth } from "@/components/providers/auth.tsx";

interface ChatProps {
  onThreadIdChange?: (threadId: string) => void;
  onThreadReady?: (thread: UseStream<GraphState>) => void;
}

const Chat: React.FC<ChatProps> = ({ onThreadIdChange, onThreadReady }) => {
  const navigate = useNavigate();
  const { threadId } = useParams<{ threadId?: string }>();
  const { token } = useAuth();
  const thread = useStream<GraphState>({
    apiUrl: `${window.location.protocol}//${window.location.host}/api`,
    assistantId: "giga_agent",
    messagesKey: "messages",
    reconnectOnMount: true,
    threadId: threadId === undefined ? null : threadId,
    fetchStateHistory: true,
    throttle: 75,
    apiKey: token,
    defaultHeaders: {
      Authorization: `Bearer ${token}`,
    },
    onThreadId: (threadId: string) => {
      onThreadIdChange?.(threadId);
      navigate(`/threads/${threadId}`);
    },
    onCustomEvent: (event, options) => {
      options.mutate((prev) => {
        // @ts-ignore
        const ui = uiMessageReducer(prev.ui ?? [], event);
        return { ...prev, ui };
      });
    },
  });

  useEffect(() => {
    onThreadReady?.(thread as unknown as UseStream<GraphState>);
  }, [thread, onThreadReady]);

  useEffect(() => {
    if (threadId) {
      onThreadIdChange?.(threadId);
    }
  }, [threadId, onThreadIdChange]);

  const stableMessages = useStableMessages(thread);

  return (
    <SelectedAttachmentsProvider>
      <div className="w-full flex p-5 max-[900px]:p-0 max-[900px]:mt-[75px]">
        <div className="flex max-w-[900px] mx-auto h-full flex-col flex-1 bg-card text-card-foreground backdrop-blur-2xl rounded-lg overflow-hidden shadow-lg dark:shadow-2xl max-[900px]:shadow-none print:overflow-visible print:shadow-none dark:print:shadow-none">
          <MessageList messages={stableMessages ?? []} thread={thread} />
          <InputArea thread={thread} />
        </div>
      </div>
    </SelectedAttachmentsProvider>
  );
};

export default Chat;
