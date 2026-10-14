import type { Message } from "@langchain/langgraph-sdk";

import type { GraphState, PlanTodo } from "../../interfaces";

export const PRESENT_PLAN_TOOL_NAME = "present_plan";

const stubMessageId = (toolCallId: string) => `exp-toolstub-${toolCallId}`;
const toolMessageId = (toolCallId: string) => `exp-toolmsg-${toolCallId}`;

export const findPresentPlanToolCallId = (
  messages: Message[],
): string | undefined => {
  for (let index = messages.length - 1; index >= 0; index--) {
    const call = ((messages[index] as any).tool_calls ?? []).find(
      (toolCall: { id?: string; name?: string }) =>
        toolCall.name === PRESENT_PLAN_TOOL_NAME,
    );
    if (call?.id) return call.id;
  }
  return undefined;
};

/**
 * Добавить утверждённый план тем же сообщением, которое немедленно коммитит
 * experimental interrupt_node. Совпадающие id позволяют серверному values
 * заменить optimistic state без исчезновения карточки.
 */
const appendPlanResult =
  (
    toolCallId: string | undefined,
    carrierExists: boolean,
    planContent: string,
    todos: PlanTodo[],
    approved: boolean,
  ) =>
  (prev: GraphState): Partial<GraphState> => {
    if (!toolCallId) return {};

    const extra: Message[] = [];
    if (!carrierExists) {
      extra.push({
        type: "ai",
        id: stubMessageId(toolCallId),
        content: "",
        additional_kwargs: { rendered: true },
        tool_calls: [
          {
            id: toolCallId,
            name: PRESENT_PLAN_TOOL_NAME,
            args: {},
            type: "tool_call",
          },
        ],
      } as unknown as Message);
    }
    extra.push({
      type: "tool",
      id: toolMessageId(toolCallId),
      tool_call_id: toolCallId,
      name: PRESENT_PLAN_TOOL_NAME,
      status: "success",
      content: approved ? "План подтверждён." : "План отменён.",
      additional_kwargs: {
        tool_name: PRESENT_PLAN_TOOL_NAME,
        response_widget: true,
        planning: {
          type: approved ? "approved_plan" : "rejected_plan",
          plan_content: planContent,
          todos,
        },
      },
    } as unknown as Message);

    return {
      ...prev,
      messages: [...(prev.messages ?? []), ...extra],
      mode: approved ? "normal" : "plan",
      plan_approved: approved,
    };
  };

export const appendApprovedPlanResult = (
  toolCallId: string | undefined,
  carrierExists: boolean,
  planContent: string,
  todos: PlanTodo[],
) => appendPlanResult(toolCallId, carrierExists, planContent, todos, true);

export const appendRejectedPlanResult = (
  toolCallId: string | undefined,
  carrierExists: boolean,
  planContent: string,
  todos: PlanTodo[],
) => appendPlanResult(toolCallId, carrierExists, planContent, todos, false);
