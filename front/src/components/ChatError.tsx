// ThinkingIndicator.tsx
import { RefreshCw } from "lucide-react";
import React from "react";
import styled from "styled-components";
import type { UseStream } from "@langchain/langgraph-sdk/react";
import { GraphState } from "@/interfaces.ts";

// Стили для переливающегося текста
const Wrapper = styled.div`
  padding: 10px 34px;
`;

const Inner = styled.div`
  background: #ee3e36;
  padding: 15px 10px;
  border-radius: 8px;
  border: 3px solid firebrick;
  display: flex;
  align-items: center;
  color: white;
`;

const RefreshButton = styled.div`
  padding: 5px;
  border-radius: 8px;
  margin-left: 4px;
  padding-bottom: 3px;
  cursor: pointer;
  transition: background-color 0.2s;
  &:hover {
    background: #d33831;
  }
`;

interface ChatErrorProps {
  thread?: UseStream<GraphState>;
}

const ChatError = ({ thread }: ChatErrorProps) => {
  if (!thread?.error || thread.isLoading) {
    return null;
  }

  return (
    <Wrapper>
      <Inner>
        В чате произошла ошибка{" "}
        <RefreshButton
          onClick={
            // @ts-ignore
            () => thread?.submit()
          }
        >
          <RefreshCw color={"white"} size={16} />
        </RefreshButton>
      </Inner>
    </Wrapper>
  );
};

export default ChatError;
