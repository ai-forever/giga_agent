import React from "react";
import Chat from "./Chat";
import { GraphState } from "../interfaces";
import type { UseStream } from "@langchain/langgraph-sdk/react";

interface ExperimentalChatProps {
  onThreadIdChange?: (threadId: string) => void;
  onThreadReady?: (thread: UseStream<GraphState>) => void;
  onRequestReload?: () => void;
}

/**
 * Экспериментальный режим (GIGA_AGENT_EXPERIMENTAL_MODE). Переиспользует основной
 * Chat, но подключается к графу-обёртке `giga_agent_experimental`, который
 * прогоняет реальный `giga_agent` в фоне, переписывает ответы и пушит статусы в
 * строку «Думаю…» (см. ThinkingIndicator).
 */
const ExperimentalChat: React.FC<ExperimentalChatProps> = (props) => {
  return <Chat {...props} assistantId="giga_agent_experimental" />;
};

export default ExperimentalChat;
