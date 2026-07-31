import React from "react";
import type { Message } from "@langchain/langgraph-sdk";
import type { ToolCall } from "@langchain/core/messages/tool";
import type { UseStream } from "@langchain/langgraph-sdk/react";

import type { GraphState, PlanningSnapshot } from "../../interfaces";
import { getScheduledTaskId } from "../scheduler/detect";
import { ApprovedPlanCard, RejectedPlanCard } from "../PlanApprovalCard";
import { ComposedBoard } from "./kit";
import {
  compositionFor,
  compositionFromResult,
  resolveWidget,
} from "./registry";

const McpUiWidget = React.lazy(() => import("../attachments/McpUiWidget"));
const SchedulerTaskChatCard = React.lazy(
  () => import("../scheduler/chat-card"),
);

/**
 * Один результат тула, помеченный как `response_widget` (см. registry.isResponseWidget).
 * Собирается в MessageList.collectResponseWidgets.
 */
export interface ResponseWidgetItem {
  toolCall: ToolCall;
  result?: Message;
}

interface ResponseWidgetProps {
  item: ResponseWidgetItem;
  thread?: UseStream<GraphState>;
  isStreaming: boolean;
}

/**
 * Диспетчер рендера результата, вынесенного ВНЕ agent-рана. Провайдер-agnostic:
 * маршрут выбирается по содержимому результата в порядке приоритета —
 * MCP-апп → карточка планировщика → генеративная доска → genui-виджет по маркеру.
 * `response_widget` (бэк) отвечает лишь за РАЗМЕЩЕНИЕ; ЧТО рисовать — решается здесь.
 */
const ResponseWidget: React.FC<ResponseWidgetProps> = ({
  item,
  thread,
  isStreaming,
}) => {
  const { toolCall, result } = item;
  const ak = (result?.additional_kwargs as any) ?? {};

  // MCP-апп(ы): один результат может нести несколько mcp_ui-аттачментов.
  const mcpAtts = ((ak.tool_attachments as any[]) ?? []).filter(
    (a) => a?.file_type === "mcp_ui" && a?.resource_uri,
  );
  if (mcpAtts.length) {
    return (
      <React.Suspense
        fallback={
          <div className="text-xs text-muted-foreground">Загрузка виджета…</div>
        }
      >
        {mcpAtts.map((att, i) => (
          <McpUiWidget
            key={`${att.resource_uri ?? "w"}-${i}`}
            serverRef={att.server_id ?? att.server}
            resourceUri={att.resource_uri}
            toolName={att.tool}
            appName={att.server}
            iconUrl={att.icon}
            toolArgs={att.tool_args}
            structuredContent={att.structured_content}
          />
        ))}
      </React.Suspense>
    );
  }

  // Карточка отложенной/периодической задачи.
  const taskId = getScheduledTaskId(result);
  if (taskId) {
    return (
      <React.Suspense fallback={null}>
        <SchedulerTaskChatCard taskId={taskId} />
      </React.Suspense>
    );
  }

  // Подтверждённый план остаётся самостоятельной карточкой и в истории.
  const planning = ak.planning as PlanningSnapshot | undefined;
  if (planning?.type === "approved_plan") {
    return (
      <ApprovedPlanCard
        planContent={planning.plan_content}
        todos={planning.todos}
      />
    );
  }
  if (planning?.type === "rejected_plan") {
    return (
      <RejectedPlanCard
        planContent={planning.plan_content}
        todos={planning.todos}
      />
    );
  }

  // Генеративная доска: из результата (персистентно) или из thread.values.ui (лайв).
  const composition =
    compositionFromResult(result) ?? compositionFor(thread, toolCall.id);
  if (composition) {
    return <ComposedBoard composition={composition} />;
  }

  // Статический genui-виджет по маркеру `widget` в payload.
  const Widget = resolveWidget(result);
  if (Widget) {
    return (
      <Widget
        toolCall={toolCall}
        resultMessage={result}
        isStreaming={isStreaming}
        thread={thread}
      />
    );
  }

  return null;
};

export default ResponseWidget;
