import type React from "react";
import type { Message } from "@langchain/langgraph-sdk";
import type { ToolCall } from "@langchain/core/messages/tool";

import BoardWidget from "./BoardWidget";

/**
 * Реестр GenUI-виджетов — маршрутизация по МАРКЕРУ payload, а не по имени тула.
 * Любой провайдер (Яндекс.Трекер, демо-трекер, будущие Jira/Linear), вернувший
 * нормализованный `{ widget: "issue_board", … }`, рендерится китом БЕЗ правок
 * фронта. В этом весь смысл: новый трекер = ноль нового фронта.
 *
 * (run_deep_research остаётся отдельным кейсом в ToolCallsList — он завязан на
 * стриминговый прогресс через thread.values.ui.)
 */
export interface WidgetProps {
  toolCall: ToolCall;
  resultMessage?: Message;
  isStreaming: boolean;
}

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

/** Подбирает виджет по маркеру `widget` в результате тула (или null). */
export function resolveWidget(
  resultMessage?: Message,
): React.FC<WidgetProps> | null {
  const kind = payloadWidgetKind(resultMessage);
  if (kind && WIDGET_KIND_REGISTRY[kind]) return WIDGET_KIND_REGISTRY[kind];
  return null;
}
