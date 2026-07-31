import React, { useId, useState } from "react";
import {
  Check,
  ChevronDown,
  ChevronUp,
  ListChecks,
  RefreshCw,
  X,
} from "lucide-react";

import type { PlanTodo } from "../interfaces";
import TextMarkdown from "./attachments/TextMarkdown";

export interface PlanApprovalResolve {
  action: "approve" | "reject";
  feedback?: string;
}

const PlanDetails: React.FC<{
  planContent: string;
  todos: PlanTodo[];
}> = ({ planContent, todos }) => {
  const [expanded, setExpanded] = useState(false);
  const detailsId = useId();

  return (
    <div className="border-t border-border/30 pt-3">
      <div className="relative">
        <div
          id={detailsId}
          className={[
            "overflow-hidden transition-[max-height] duration-300",
            expanded ? "max-h-none" : "max-h-40",
          ].join(" ")}
        >
          <div className="text-sm [&_h1]:!mb-2 [&_h1]:!text-lg [&_h2]:!mt-3 [&_h2]:!mb-2 [&_h2]:!text-base [&_h3]:!mt-3 [&_h3]:!mb-2 [&_h3]:!text-sm [&_h4]:!my-2 [&_h4]:!text-sm [&_h5]:!my-2 [&_h5]:!text-sm [&_h6]:!my-2 [&_h6]:!text-sm">
            <TextMarkdown>{planContent}</TextMarkdown>
          </div>
          {todos.length > 0 && (
            <div className="mt-2 border-t border-border/30 pt-2">
              <div className="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
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
          )}
        </div>
        {!expanded && (
          <div
            className="pointer-events-none absolute inset-x-0 bottom-0 h-12 bg-gradient-to-t from-card/90 to-transparent"
            aria-hidden
          />
        )}
      </div>
      <button
        type="button"
        aria-expanded={expanded}
        aria-controls={detailsId}
        onClick={() => setExpanded((value) => !value)}
        className="mt-1 inline-flex cursor-pointer items-center gap-1 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
      >
        {expanded ? (
          <ChevronUp className="size-3.5" />
        ) : (
          <ChevronDown className="size-3.5" />
        )}
        {expanded ? "Свернуть план" : "Развернуть план"}
      </button>
    </div>
  );
};

export const ApprovedPlanCard: React.FC<{
  planContent: string;
  todos: PlanTodo[];
}> = ({ planContent, todos }) => (
  <div className="mt-2 mb-2 overflow-hidden rounded-lg border border-border/60 bg-muted/10">
    <div className="p-4">
      <div className="mb-2 flex items-center gap-2">
        <Check className="size-4 text-emerald-500" />
        <span className="text-sm font-medium text-foreground">
          План подтверждён
        </span>
        {todos.length > 0 && (
          <span className="ml-auto text-xs text-muted-foreground">
            {todos.length} шаг(ов)
          </span>
        )}
      </div>
      <PlanDetails planContent={planContent} todos={todos} />
    </div>
  </div>
);

export const RejectedPlanCard: React.FC<{
  planContent: string;
  todos: PlanTodo[];
}> = ({ planContent, todos }) => (
  <div className="mt-2 mb-2 overflow-hidden rounded-lg border border-border/60 bg-muted/10">
    <div className="p-4">
      <div className="mb-2 flex items-center gap-2">
        <X className="size-4 text-muted-foreground" />
        <span className="text-sm font-medium text-foreground">
          План отменён
        </span>
        {todos.length > 0 && (
          <span className="ml-auto text-xs text-muted-foreground">
            {todos.length} шаг(ов)
          </span>
        )}
      </div>
      <PlanDetails planContent={planContent} todos={todos} />
    </div>
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
    <div className="mt-2 mb-2 overflow-hidden rounded-lg border border-border/60 bg-muted/10">
      <div className="p-4 pb-3">
        <div className="mb-2 flex items-center gap-2">
          <ListChecks className="size-4 text-primary" />
          <span className="text-sm font-medium text-foreground">
            План готов — подтвердите
          </span>
          {todos.length > 0 && (
            <span className="ml-auto text-xs text-muted-foreground">
              {todos.length} шаг(ов)
            </span>
          )}
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
      </div>

      <div className="flex flex-wrap items-center justify-end gap-2 border-t border-border/30 bg-muted/5 px-4 py-3">
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
