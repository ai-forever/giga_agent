import type React from "react";
import type { Message } from "@langchain/langgraph-sdk";
import type { ToolCall } from "@langchain/core/messages/tool";

import IssueBoard from "./IssueBoard";

/**
 * Реестр GenUI-виджетов: имя тула → React-компонент, который рисует результат
 * этого тула как интерактивный UI вместо дефолтного JSON-дропа.
 *
 * Чтобы добавить виджет под новый тул — просто зарегистрируй его здесь.
 * (run_deep_research остаётся отдельным кейсом в ToolCallsList: он глубоко
 * завязан на стриминговый прогресс через thread.values.ui.)
 */
export interface WidgetProps {
  toolCall: ToolCall;
  resultMessage?: Message;
  isStreaming: boolean;
}

export const WIDGET_REGISTRY: Record<string, React.FC<WidgetProps>> = {
  tracker_search_issues: IssueBoard,
  tracker_get_issue: IssueBoard,
};
