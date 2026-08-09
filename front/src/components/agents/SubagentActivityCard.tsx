import React, { useState } from "react";
import { Bot, CircleCheck, CircleX, Loader2, Minus, Plus } from "lucide-react";

const SubagentChat = React.lazy(() => import("./SubagentChat"));

export type SubagentActivity = {
  agent_id: string;
  agent_name?: string;
  task?: string;
  child_thread_id?: string;
  child_run_id?: string;
  tool_call_id?: string;
  status:
    | "running"
    | "interrupted"
    | "completed"
    | "cancelled"
    | "error"
    | "expired"
    | "needs_setup";
  started_at?: number;
  finished_at?: number;
  duration?: number;
  result?: string;
  error?: string;
  error_code?: string;
  items?: { type: string; name?: string; status?: string; text?: string }[];
};

const label: Record<SubagentActivity["status"], string> = {
  running: "Выполняется",
  interrupted: "Ждёт подтверждения",
  completed: "Завершён",
  cancelled: "Отменён",
  error: "Ошибка",
  expired: "Истёк",
  needs_setup: "Нужна настройка",
};

const SubagentActivityCard: React.FC<{
  activity: SubagentActivity;
  live?: boolean;
}> = ({ activity, live = false }) => {
  const [expanded, setExpanded] = useState(false);
  const duration =
    activity.duration ??
    (activity.started_at ? Date.now() / 1000 - activity.started_at : null);
  const statusIcon =
    activity.status === "running" ? (
      <Loader2 className="size-4 animate-spin" />
    ) : activity.status === "completed" ? (
      <CircleCheck className="size-4 text-emerald-500" />
    ) : (
      <CircleX className="size-4 text-destructive" />
    );
  const agentName = activity.agent_name || activity.agent_id;

  return (
    <div className="mb-3 px-[20px]">
      <div
        className={`flex flex-col overflow-hidden rounded-lg border border-border bg-card ${
          expanded ? "h-[350px]" : "min-h-[76px]"
        }`}
      >
        <button
          type="button"
          aria-expanded={expanded}
          aria-controls={
            activity.child_thread_id
              ? `subagent-chat-${activity.tool_call_id ?? activity.child_thread_id}`
              : undefined
          }
          className="flex shrink-0 items-center gap-2 px-3 py-2 text-left hover:bg-muted/30"
          onClick={() => setExpanded((value) => !value)}
        >
          {expanded ? (
            <Minus className="size-4 shrink-0" />
          ) : (
            <Plus className="size-4 shrink-0" />
          )}
          <Bot className="size-4 shrink-0" />
          <div className="min-w-0 flex-1">
            <div className="text-[11px] text-muted-foreground">
              Вызов суб-агента
            </div>
            <div className="truncate text-sm font-medium">{agentName}</div>
            <div
              className="line-clamp-2 text-xs text-muted-foreground"
              title={activity.task}
            >
              {activity.task || "Задача не указана"}
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <span className="hidden text-[11px] text-muted-foreground sm:inline">
              {label[activity.status]}
              {live && activity.status === "running" ? " · live" : ""}
              {duration !== null
                ? ` · ${Math.max(0, duration).toFixed(1)} с`
                : ""}
            </span>
            {statusIcon}
          </div>
        </button>

        {expanded && (
          <div
            id={
              activity.child_thread_id
                ? `subagent-chat-${activity.tool_call_id ?? activity.child_thread_id}`
                : undefined
            }
            className="min-h-0 flex-1 border-t border-border/70"
          >
            {activity.child_thread_id ? (
              <React.Suspense
                fallback={
                  <div className="p-3 text-xs text-muted-foreground">
                    Загрузка чата суб-агента…
                  </div>
                }
              >
                <SubagentChat threadId={activity.child_thread_id} />
              </React.Suspense>
            ) : (
              <div className="grid gap-1 overflow-y-auto p-3 text-xs">
                <div className="text-muted-foreground">
                  {label[activity.status]}
                </div>
                {(activity.error || activity.error_code) && (
                  <div className="text-destructive">
                    {activity.error_code ? `${activity.error_code}: ` : ""}
                    {activity.error}
                  </div>
                )}
                {activity.result && (
                  <pre className="whitespace-pre-wrap text-foreground">
                    {activity.result}
                  </pre>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default SubagentActivityCard;
