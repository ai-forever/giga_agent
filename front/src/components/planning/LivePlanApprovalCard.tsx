import React, { useState } from "react";
import type { UseStream } from "@langchain/langgraph-sdk/react";

import type { GraphState, GraphTemplate, PlanTodo } from "../../interfaces";
import PlanApprovalCard, {
  type PlanApprovalResolve,
} from "../PlanApprovalCard";
import {
  appendApprovedPlanResult,
  appendRejectedPlanResult,
  findPresentPlanToolCallId,
} from "./optimistic";

/**
 * Active `plan_approval` interrupt rendered outside agent runs.
 *
 * `present_plan` may be the last step of a collapsible run, but the decision
 * controls the whole stream and must remain visible even when that run is
 * collapsed. This mirrors the placement of LiveQuestionsForm.
 */
const LivePlanApprovalCard: React.FC<{
  thread?: UseStream<GraphState, GraphTemplate>;
}> = ({ thread }) => {
  const [handled, setHandled] = useState(false);
  const interrupt = thread?.interrupt?.value;
  const planContent =
    interrupt?.type === "plan_approval" ? (interrupt.plan_content ?? "") : "";
  const todos =
    interrupt?.type === "plan_approval" ? (interrupt.todos ?? []) : [];

  if (
    !interrupt ||
    interrupt.type !== "plan_approval" ||
    handled ||
    thread?.isLoading
  ) {
    return null;
  }

  const handleResolve = (payload: PlanApprovalResolve) => {
    setHandled(true);
    const carrierToolCallId = findPresentPlanToolCallId(thread?.messages ?? []);
    const toolCallId = carrierToolCallId ?? interrupt.tool_call_id;
    thread?.submit(undefined, {
      command: { resume: payload },
      optimisticValues:
        payload.action === "approve"
          ? appendApprovedPlanResult(
              toolCallId,
              Boolean(carrierToolCallId),
              planContent,
              todos as PlanTodo[],
            )
          : appendRejectedPlanResult(
              toolCallId,
              Boolean(carrierToolCallId),
              planContent,
              todos as PlanTodo[],
            ),
      onDisconnect: "continue",
    });
  };

  return (
    <div className="px-[20px]">
      <PlanApprovalCard
        planContent={planContent}
        todos={todos as PlanTodo[]}
        onResolve={handleResolve}
      />
    </div>
  );
};

export default LivePlanApprovalCard;
