import React, { useState } from "react";
import { Check, ListChecks, RefreshCw, X } from "lucide-react";

import type { PlanTodo } from "../interfaces";
import TextMarkdown from "./attachments/TextMarkdown";

export interface PlanApprovalResolve {
  action: "approve" | "reject";
  feedback?: string;
}

const PlanDetails: React.FC<{
  planContent: string;
  todos: PlanTodo[];
}> = ({ planContent, todos }) => (
  <>
    <div className="border-t border-border pt-3 text-sm">
      <TextMarkdown>{planContent}</TextMarkdown>
    </div>
    <div className="mt-3 border-t border-border pt-3">
      <div className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        Шаги
      </div>
      <div className="flex flex-col gap-1.5">
        {todos.map((todo) => (
          <div key={todo.id} className="flex items-start gap-2 text-sm">
            <span
              className="mt-[7px] inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-muted-foreground/40"
              aria-hidden
            />
            <div className="min-w-0">
              <div className="text-foreground">{todo.content}</div>
              {todo.note && (
                <div className="mt-0.5 text-xs text-muted-foreground">
                  {todo.note}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  </>
);

export const ApprovedPlanCard: React.FC<{
  planContent: string;
  todos: PlanTodo[];
}> = ({ planContent, todos }) => (
  <div className="mt-1 mb-2 rounded-xl border border-emerald-500/30 bg-muted/10 p-3">
    <div className="mb-2 flex items-center gap-2">
      <Check className="size-4 text-emerald-500" />
      <span className="text-sm font-medium text-foreground">
        План подтверждён
      </span>
      <span className="ml-auto text-xs text-muted-foreground">
        {todos.length} шаг(ов)
      </span>
    </div>
    <PlanDetails planContent={planContent} todos={todos} />
  </div>
);

const PlanApprovalCard: React.FC<{
  planContent: string;
  todos: PlanTodo[];
  disabled?: boolean;
  loading?: boolean;
  onResolve: (payload: PlanApprovalResolve) => void;
}> = ({ planContent, todos, disabled, loading, onResolve }) => {
  const [rejecting, setRejecting] = useState(false);
  const [feedback, setFeedback] = useState("");
  const trimmedFeedback = feedback.trim();

  const handleReject = () => {
    if (!rejecting) {
      setRejecting(true);
      return;
    }
    if (!trimmedFeedback) return;
    onResolve({ action: "reject", feedback: trimmedFeedback });
  };

  return (
    <div className="mt-1 mb-2 rounded-xl border border-primary/30 bg-muted/10 p-3">
      <div className="mb-2 flex items-center gap-2">
        <ListChecks className="size-4 text-primary" />
        <span className="text-sm font-medium text-foreground">
          План готов — подтвердите
        </span>
        <span className="ml-auto text-xs text-muted-foreground">
          {todos.length} шаг(ов)
        </span>
      </div>

      <PlanDetails planContent={planContent} todos={todos} />

      {rejecting && (
        <textarea
          value={feedback}
          onChange={(event) => setFeedback(event.target.value)}
          placeholder="Что нужно изменить в плане?"
          rows={3}
          autoFocus
          className="mt-3 w-full resize-none rounded-lg border border-border bg-background px-2 py-1.5 text-sm outline-none focus:border-primary/50"
        />
      )}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => onResolve({ action: "approve" })}
          disabled={disabled}
          className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground transition-[filter] hover:brightness-110 disabled:opacity-60"
        >
          {loading ? (
            <RefreshCw className="size-4 animate-spin" />
          ) : (
            <Check className="size-4" />
          )}
          Подтвердить
        </button>
        <button
          type="button"
          onClick={handleReject}
          disabled={disabled || (rejecting && !trimmedFeedback)}
          className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-muted/40 disabled:cursor-not-allowed disabled:opacity-60"
        >
          <X className="size-4" />
          {rejecting ? "Отправить замечания" : "Отклонить"}
        </button>
      </div>
    </div>
  );
};

export default PlanApprovalCard;
