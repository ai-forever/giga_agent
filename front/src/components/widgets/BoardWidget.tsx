import React, { useMemo } from "react";
import type { Message } from "@langchain/langgraph-sdk";
import type { ToolCall } from "@langchain/core/messages/tool";

import { Board, WidgetShell, EmptyState } from "./kit";
import type { Issue, IssueBoardPayload } from "./kit";

/**
 * Генеричный драйвер «доски задач», маршрутизируемый по маркеру payload
 * (`widget: "issue_board"`), а НЕ по имени тула. Любой провайдер (Jira, Linear,
 * мок…), вернувший нормализованный IssueBoardPayload, рендерится этим виджетом
 * без единой правки фронта — в этом весь смысл контракта.
 */
const BoardWidget: React.FC<{
  toolCall: ToolCall;
  resultMessage?: Message;
  isStreaming: boolean;
}> = ({ resultMessage, isStreaming }) => {
  const payload = useMemo<IssueBoardPayload | null>(() => {
    if (!resultMessage) return null;
    try {
      const raw =
        typeof resultMessage.content === "string"
          ? JSON.parse(resultMessage.content)
          : resultMessage.content;
      const inner = (raw?.data ?? raw) as IssueBoardPayload;
      return inner?.widget === "issue_board" ? inner : null;
    } catch {
      return null;
    }
  }, [resultMessage]);

  if (!resultMessage) {
    return (
      <WidgetShell>
        <EmptyState loading={isStreaming}>Загрузка задач…</EmptyState>
      </WidgetShell>
    );
  }
  if (!payload) {
    return (
      <WidgetShell>
        <EmptyState tone="error">Некорректный ответ виджета</EmptyState>
      </WidgetShell>
    );
  }

  // Гарантируем provider на каждой задаче (StatusBadge строит из него REST).
  const issues: Issue[] = (payload.issues ?? []).map((it) => ({
    ...it,
    provider: it.provider || payload.provider,
  }));

  return (
    <Board issues={issues} groupBy={payload.groupBy} error={payload.error} />
  );
};

export default BoardWidget;
