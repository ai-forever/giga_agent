import type React from "react";
import type { Message } from "@langchain/langgraph-sdk";
import type { ToolCall } from "@langchain/core/messages/tool";
import type { UseStream } from "@langchain/langgraph-sdk/react";

import type { GraphState } from "../../interfaces";
import type { Composition } from "./kit";
import BoardWidget from "./BoardWidget";
import FileBrowser from "./FileBrowser";
import MailInbox from "./MailInbox";
import CalendarAgenda from "./CalendarAgenda";
import MonthGrid from "./MonthGrid";
import ActivityPill from "./ActivityPill";

// Имя pushed-UI генеративной доски (совпадает с tracker_base.COMPOSED_UI).
export const COMPOSED_BOARD_UI = "issue_board_composed";

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
  file_browser: FileBrowser,
  mail_inbox: MailInbox,
  calendar_agenda: CalendarAgenda,
  calendar_month: MonthGrid,
  // Маркер активности экспериментального режима (пилюля «Работал N»).
  experimental_activity: ActivityPill,
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

// Достаёт композицию генеративной доски из thread.values.ui по tool_call_id
// (лайв во время стрима, пока результат тула ещё не персистентен).
export function compositionFor(
  thread: UseStream<GraphState> | undefined,
  toolCallId: string | undefined,
): Composition | null {
  if (!thread || !toolCallId) return null;
  // @ts-ignore — ui не типизирован в GraphState
  const uis = (thread.values?.ui ?? []).filter(
    (el: any) =>
      el.name === COMPOSED_BOARD_UI && el.props?.tool_call_id === toolCallId,
  );
  const last = uis.at(-1);
  return (last?.props?.composition as Composition) ?? null;
}

// Композиция из РЕЗУЛЬТАТА тула (персистентный источник, в отличие от
// thread.values.ui, который живёт только во время стрима).
export function compositionFromResult(
  resultMessage?: Message,
): Composition | null {
  if (!resultMessage) return null;
  try {
    const raw =
      typeof resultMessage.content === "string"
        ? JSON.parse(resultMessage.content)
        : resultMessage.content;
    const inner = (raw as any)?.data ?? raw;
    if ((inner as any)?.view !== "composed_board") return null;
    return ((inner as any)?.composition as Composition) ?? null;
  } catch {
    return null;
  }
}

/**
 * Сигнал РАЗМЕЩЕНИЯ: результат тула нужно рендерить самостоятельным виджетом
 * ВНЕ схлопывающегося agent-рана. Ставится бэком в
 * `additional_kwargs.response_widget` (см. build_widget_tool_message) либо
 * выводится из наличия mcp_ui-аттачмента (MCP-апп всегда рендерится как виджет).
 * КАКОЙ компонент рисовать — решает ResponseWidget по содержимому результата.
 */
export function isResponseWidget(result?: Message): boolean {
  const ak = (result?.additional_kwargs as any) ?? {};
  if (ak.response_widget === true) return true;
  const atts = (ak.tool_attachments as any[]) ?? [];
  return atts.some((a) => a?.file_type === "mcp_ui" && a?.resource_uri);
}
