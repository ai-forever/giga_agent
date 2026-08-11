import React, { useEffect, useRef } from "react";
import { uiMessageReducer } from "@langchain/langgraph-sdk/react-ui";
import { useStream, type UseStream } from "@langchain/langgraph-sdk/react";

import { API_BASE_URL } from "@/config";
import { useAuth } from "@/components/providers/auth";
import MessageList from "@/components/MessageList";
import type { GraphState } from "@/interfaces";

const disableAutoScroll = () => {};

const SubagentChat: React.FC<{ threadId: string }> = ({ threadId }) => {
  const { token } = useAuth();
  const thread = useStream<GraphState>({
    apiUrl: `${API_BASE_URL}/`,
    assistantId: "giga_agent",
    messagesKey: "messages",
    reconnectOnMount: true,
    threadId,
    fetchStateHistory: false,
    throttle: 10,
    apiKey: token,
    defaultHeaders: {
      Authorization: `Bearer ${token}`,
    },
    onCustomEvent: (event, options) => {
      options.mutate((previous) => {
        // @ts-ignore LangGraph UI messages are intentionally open-ended.
        const ui = uiMessageReducer(previous.ui ?? [], event);
        return { ...previous, ui };
      });
    },
  }) as unknown as UseStream<GraphState>;

  const threadRef = useRef(thread);
  threadRef.current = thread;

  // reconnectOnMount covers the usual case. This explicit lookup also joins a
  // child run that was started before the collapsed card was opened.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const runs = await threadRef.current.client.runs.list(threadId, {
          limit: 1,
        });
        const latest = runs[0] as
          | { run_id: string; status: string }
          | undefined;
        if (
          !cancelled &&
          latest &&
          (latest.status === "running" || latest.status === "pending")
        ) {
          // @ts-ignore joinStream is available at runtime but missing in SDK types.
          threadRef.current.joinStream(latest.run_id);
        }
      } catch {
        // The child may finish between the state and runs requests; its state
        // remains available through the initial useStream load.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [threadId]);

  return (
    <div className="h-full overflow-y-auto" style={{ zoom: 0.8 }}>
      <MessageList
        messages={thread.messages ?? []}
        thread={thread}
        threadId={threadId}
        maybeAutoScroll={disableAutoScroll}
        notShowWelcomeMessage
        compact
        readOnly
      />
      {thread.interrupt && (
        <div className="border-t border-border/60 px-2 py-1 text-[11px] text-amber-600">
          Суб-агент ожидает подтверждения в родительском чате.
        </div>
      )}
    </div>
  );
};

export default SubagentChat;
