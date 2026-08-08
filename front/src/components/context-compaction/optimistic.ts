import type { Message } from "@langchain/langgraph-sdk";

import type { GraphState } from "../../interfaces";

export const contextCompactionStartedMessageId = (operationId: string) =>
  `context-compaction-started-${operationId}`;

const STARTED_MESSAGE =
  "Начинаю суммаризацию контекста. Это служебный шаг, скоро покажу результат.";

export const buildContextCompactionStartedMessage = (
  operationId: string,
): Message =>
  ({
    type: "ai",
    id: contextCompactionStartedMessageId(operationId),
    content: STARTED_MESSAGE,
    additional_kwargs: {
      rendered: true,
      kind: "system_notice",
      giga_agent: {
        context_compaction: {
          version: 1,
          status: "started",
          operation_id: operationId,
          reason: "manual",
        },
      },
    },
  }) as unknown as Message;

export const appendContextCompactionStarted =
  (operationId: string, sourceMessages?: Message[]) =>
  (prev: GraphState): Partial<GraphState> => {
    const message = buildContextCompactionStartedMessage(operationId);
    const baseMessages = sourceMessages ?? prev.messages ?? [];
    if (baseMessages.some((item) => item.id === message.id)) {
      return { ...prev, messages: baseMessages };
    }
    return { ...prev, messages: [...baseMessages, message] };
  };
