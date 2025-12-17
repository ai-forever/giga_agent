// ThinkingIndicator.tsx
import React from "react";
import { Message as Message_ } from "@langchain/langgraph-sdk";
import type { UseStream } from "@langchain/langgraph-sdk/react";
import { GraphState } from "../interfaces.ts";

interface ThinkingProps {
  messages: Message_[];
  thread?: UseStream<GraphState>;
}

const ThinkingIndicator = ({ messages, thread }: ThinkingProps) => {
  if (
    messages.length <= 0 ||
    messages[messages.length - 1].type === "ai" ||
    !thread?.isLoading
  ) {
    return null;
  }
  return (
    <div className="px-[34px] py-[10px] text-transparent bg-gradient-to-r from-foreground/40 via-foreground to-foreground/40 bg-clip-text animate-pulse">
      Думаю…
    </div>
  );
};

export default ThinkingIndicator;
