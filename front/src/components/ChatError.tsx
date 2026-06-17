// ThinkingIndicator.tsx
import { RefreshCw } from "lucide-react";
import React, { useEffect, useRef } from "react";
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
  // Защита от двойного клика: submit асинхронный, между кликом и переходом
  // thread.isLoading в true есть окно, в котором кнопка ещё видна и повторные
  // клики успели бы запустить несколько ранов. Ref закрывает это окно, а когда
  // ран подхватился (isLoading) — снимаем защиту для будущих ретраев.
  const submittingRef = useRef(false);
  useEffect(() => {
    if (thread?.isLoading) {
      submittingRef.current = false;
    }
  }, [thread?.isLoading]);

  if (!thread?.error || thread.isLoading) {
    return null;
  }

  const handleRetry = () => {
    if (submittingRef.current) return;
    submittingRef.current = true;
    // У нас fetchStateHistory: false, поэтому SDK не подставляет implicit-checkpoint
    // и submit(undefined) уходит без input/command/checkpoint. Реальный langgraph это
    // допускает (resume от последнего чекпоинта), а aegra отвечает 422
    // ("Must specify at least one of 'input', 'command', or 'checkpoint'").
    // Передаём checkpoint — aegra принимает его (это non-None dict) и, т.к.
    // input/command пустые, резюмит ран от последнего чекпоинта (pending tasks).
    // checkpoint_id/checkpoint_map = null отфильтровываются на бэке, остаётся
    // checkpoint_ns: "" — корневой неймспейс основного графа.
    void thread.submit(undefined, {
      checkpoint: {
        checkpoint_ns: "",
        checkpoint_id: null,
        checkpoint_map: null,
      },
    });
  };

  return (
    <Wrapper>
      <Inner>
        В чате произошла ошибка{" "}
        <RefreshButton onClick={handleRetry}>
          <RefreshCw color={"white"} size={16} />
        </RefreshButton>
      </Inner>
    </Wrapper>
  );
};

export default ChatError;
