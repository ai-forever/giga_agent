import React, { useEffect, useMemo, useRef, useState } from "react";
import MessageList from "../MessageList";
import InputArea from "../InputArea";
import { useStream } from "@langchain/langgraph-sdk/react";
import { useStableMessages } from "../../hooks/useStableMessages";
import { GraphState } from "@/interfaces";
import { HumanMessage } from "@langchain/langgraph-sdk";
import { useNavigate, useParams } from "react-router-dom";
import { useDemoItems } from "@/hooks/DemoItemsProvider.tsx";
import Message from "../Message.tsx";
import DemoToolBar from "./DemoToolBar.tsx";
import { uiMessageReducer } from "@langchain/langgraph-sdk/react-ui";
import { SelectedAttachmentsProvider } from "@/hooks/SelectedAttachmentsContext.tsx";
import type { UseStream } from "@langchain/langgraph-sdk/react";
import { useRagContext } from "@/components/rag/providers/RAG.tsx";
import { useSettings } from "@/components/Settings.tsx";
import { useUserInfo } from "@/components/providers/user-info.tsx";

interface DemoChatProps {
  onContinue: () => void;
  onThreadIdChange?: (threadId: string) => void;
  onThreadReady?: (thread: UseStream<GraphState>) => void;
}

const DemoChat = ({
  onContinue,
  onThreadIdChange,
  onThreadReady,
}: DemoChatProps) => {
  const navigate = useNavigate();
  const { demoIndex } = useParams<{ demoIndex: string }>();
  const { demoItems } = useDemoItems();
  const demoIndexNum = !isNaN(parseInt(demoIndex ?? "0"))
    ? parseInt(demoIndex ?? "0")
    : 0;
  const demoItem = demoItems.at(demoIndexNum);
  const listRef = useRef<any>(null);
  const [firstSent, setFirstSend] = useState(false);
  const [isFinished, setIsFinished] = useState(false);

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

  const thread = useStream<GraphState>({
    apiUrl: `${window.location.protocol}//${window.location.host}/graph`,
    assistantId: "chat",
    messagesKey: "messages",
    onThreadId: (threadId: string) => {
      onThreadIdChange?.(threadId);
    },
    onFinish: (state) => {
      if (state.next.length === 0) {
        setIsFinished(true);
      }
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

  const stableMessages = useStableMessages(thread);
  useEffect(() => {
    if (
      // @ts-ignore
      stableMessages.filter((mes) => mes.type === "ai").length >
      (demoItem?.steps ?? 10)
    ) {
      setIsFinished(true);
    }
  }, [stableMessages, demoItem]);

  const handleContinueDemo = () => {
    let nextIndex = (demoIndexNum + 1) % demoItems.length;
    while (!demoItems[nextIndex].active) {
      nextIndex = (nextIndex + 1) % demoItems.length;
    }
    navigate("/demo/" + nextIndex);
    onContinue();
  };

  return (
    <SelectedAttachmentsProvider>
      <div className="w-full flex p-5 max-[900px]:p-0 max-[900px]:mt-[75px]">
        <div className="flex max-w-[900px] mx-auto h-full flex-col flex-1 bg-card text-card-foreground backdrop-blur-2xl rounded-lg overflow-hidden shadow-lg dark:shadow-2xl max-[900px]:shadow-none print:overflow-visible print:shadow-none">
          <MessageList
            messages={stableMessages ?? []}
            thread={thread}
            ref={listRef}
            notShowWelcomeMessage={true}
          >
            {!firstSent && (
              <Message
                key={0}
                message={{
                  type: "human",
                  id: "123",
                  content: demoItem?.json_data.message ?? "",
                  // @ts-ignore
                  additional_kwargs: {
                    rendered: false,
                    files: demoItem?.json_data.attachments ?? [],
                  },
                }}
                onWrite={() => {
                  if (listRef.current) listRef.current.scrollToBottom();
                }}
                onWriteEnd={() => {
                  const newMessage = {
                    type: "human",
                    content: demoItem?.json_data.message ?? "",
                    additional_kwargs: {
                      user_input: demoItem?.json_data.message ?? "",
                      files: demoItem?.json_data.attachments ?? [],
                    },
                  } as HumanMessage;

                  thread.submit(
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
                    },
                  );
                  setFirstSend(true);
                }}
                writeMessage={true}
              />
            )}
          </MessageList>
          <InputArea thread={thread} />
        </div>
        <DemoToolBar isFinished={isFinished} onContinue={handleContinueDemo} />
      </div>
    </SelectedAttachmentsProvider>
  );
};

export default DemoChat;
