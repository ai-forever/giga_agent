import type React from "react";
import type { Message } from "@langchain/langgraph-sdk";
import type { ToolCall } from "@langchain/core/messages/tool";

import IssueBoard from "./IssueBoard";
import BoardWidget from "./BoardWidget";

/**
 * Реестр GenUI-виджетов. Два пути разрешения:
 *
 * 1. По ИМЕНИ ТУЛА (WIDGET_REGISTRY) — для провайдеров с бытовой формой ответа,
 *    которым нужен адаптер (сейчас Яндекс.Трекер → IssueBoard).
 * 2. По МАРКЕРУ PAYLOAD (WIDGET_KIND_REGISTRY) — любой тул, вернувший
 *    нормализованный `{ widget: "issue_board", … }`, рендерится китом БЕЗ новой
 *    строки реестра. Это и даёт «новый трекер = ноль нового фронта».
 *
 * (run_deep_research остаётся отдельным кейсом в ToolCallsList — он завязан на
 * стриминговый прогресс через thread.values.ui.)
 */
export interface WidgetProps {
  toolCall: ToolCall;
  resultMessage?: Message;
  isStreaming: boolean;
}

const WIDGET_REGISTRY: Record<string, React.FC<WidgetProps>> = {
  tracker_search_issues: IssueBoard,
  tracker_get_issue: IssueBoard,
};

const WIDGET_KIND_REGISTRY: Record<string, React.FC<WidgetProps>> = {
  issue_board: BoardWidget,
};

function payloadWidgetKind(resultMessage?: Message): string | null {
  if (!resultMessage) return null;
  try {
    const raw =
      typeof resultMessage.content === "string"
        ? JSON.parse(resultMessage.content)
        : resultMessage.content;
    const inner = (raw as any)?.data ?? raw;
    const kind = (inner as any)?.widget;
    return typeof kind === "string" ? kind : null;
  } catch {
    return null;
  }
}

/** Подбирает виджет для тул-вызова: имя тула → иначе маркер payload. */
export function resolveWidget(
  toolName: string,
  resultMessage?: Message,
): React.FC<WidgetProps> | null {
  const byName = WIDGET_REGISTRY[toolName];
  if (byName) return byName;
  const kind = payloadWidgetKind(resultMessage);
  if (kind && WIDGET_KIND_REGISTRY[kind]) return WIDGET_KIND_REGISTRY[kind];
  return null;
}
