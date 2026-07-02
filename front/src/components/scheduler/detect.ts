import type { Message } from "@langchain/langgraph-sdk";

// Scheduler tools whose successful result is promoted into a standalone card.
const SCHEDULER_CARD_TOOLS = new Set(["schedule_task", "edit_scheduled_task"]);
// The `status` a successful call of one of those tools reports.
const SCHEDULER_CARD_STATUSES = new Set(["scheduled", "updated"]);

/**
 * If a tool result is a successful `schedule_task` / `edit_scheduled_task` call,
 * return the affected task id; otherwise null. Only successful calls qualify
 * (errors / non-scheduler tools return null). Used to promote the result out of
 * the tool-call list and render it as a standalone scheduler card in the message
 * flow (i.e. outside the collapsible agent run).
 */
export const getScheduledTaskId = (resultMessage?: Message): string | null => {
  if (!resultMessage) return null;
  const ak = (resultMessage as any).additional_kwargs || {};
  if (!SCHEDULER_CARD_TOOLS.has(ak.tool_name)) return null;
  if ((resultMessage as any).status === "error") return null;

  let content: unknown = (resultMessage as any).content;
  if (Array.isArray(content)) {
    content = content
      .map((p) => (typeof p === "string" ? p : ((p as any)?.text ?? "")))
      .join("");
  }
  if (typeof content !== "string" || !content.trim()) return null;

  const find = (node: unknown, depth: number): string | null => {
    if (depth > 4 || node == null) return null;
    if (typeof node === "string") {
      const s = node.trim();
      if (s.startsWith("{") || s.startsWith("[")) {
        try {
          return find(JSON.parse(s), depth + 1);
        } catch {
          return null;
        }
      }
      return null;
    }
    if (Array.isArray(node)) {
      for (const it of node) {
        const r = find(it, depth + 1);
        if (r) return r;
      }
      return null;
    }
    if (typeof node === "object") {
      const obj = node as Record<string, unknown>;
      if (
        typeof obj.task_id === "string" &&
        typeof obj.status === "string" &&
        SCHEDULER_CARD_STATUSES.has(obj.status) &&
        !obj.error
      ) {
        return obj.task_id;
      }
      for (const v of Object.values(obj)) {
        const r = find(v, depth + 1);
        if (r) return r;
      }
    }
    return null;
  };

  try {
    return find(JSON.parse(content), 0);
  } catch {
    return null;
  }
};
