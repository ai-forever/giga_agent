import React, { useState } from "react";
import { Check, X, Pencil, ListChecks, RefreshCw } from "lucide-react";
import { PlanTodo } from "../interfaces";

export interface PlanApprovalResolve {
  action: "approve" | "edit" | "reject";
  plan?: PlanTodo[];
  feedback?: string;
}

// Карточка подтверждения плана (interrupt type "plan_approval").
// Approve → исполнять как есть. Изменить → правка заголовков, шлём action "edit"
// с планом. Отклонить → текстовый фидбек, агент перепланирует.
const PlanApprovalCard: React.FC<{
  plan: PlanTodo[];
  disabled?: boolean;
  loading?: boolean;
  onResolve: (payload: PlanApprovalResolve) => void;
}> = ({ plan, disabled, loading, onResolve }) => {
  const [todos, setTodos] = useState<PlanTodo[]>(() =>
    plan.map((t) => ({ ...t })),
  );
  const [editing, setEditing] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [feedback, setFeedback] = useState("");

  const updateTitle = (id: string, title: string) => {
    setDirty(true);
    setTodos((prev) => prev.map((t) => (t.id === id ? { ...t, title } : t)));
  };

  const handleApprove = () =>
    onResolve(dirty ? { action: "edit", plan: todos } : { action: "approve" });

  const handleReject = () => {
    if (!rejecting) {
      setRejecting(true);
      return;
    }
    onResolve({ action: "reject", feedback: feedback.trim() });
  };

  return (
    <div className="mt-1 mb-2 rounded-xl border border-primary/30 bg-muted/10 p-3">
      <div className="mb-1 flex items-center gap-2">
        <ListChecks className="size-4 text-primary" />
        <span className="text-sm font-medium text-foreground">
          План готов — подтвердите
        </span>
        <span className="ml-auto text-xs text-muted-foreground">
          {todos.length} шаг(ов)
        </span>
      </div>

      <div className="mb-2 flex flex-col gap-1 border-t border-border pt-2">
        {todos.map((t) => (
          <div key={t.id} className="flex items-start gap-2 text-sm">
            <span
              className="mt-[7px] inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-muted-foreground/40"
              aria-hidden
            />
            {editing ? (
              <input
                value={t.title}
                onChange={(e) => updateTitle(t.id, e.target.value)}
                className="flex-1 rounded border border-border bg-background px-2 py-1 text-sm outline-none focus:border-primary/50"
              />
            ) : (
              <span className="text-foreground">{t.title}</span>
            )}
          </div>
        ))}
      </div>

      {rejecting && (
        <textarea
          value={feedback}
          onChange={(e) => setFeedback(e.target.value)}
          placeholder="Что поправить в плане?"
          rows={2}
          autoFocus
          className="mb-2 w-full resize-none rounded-lg border border-border bg-background px-2 py-1.5 text-sm outline-none focus:border-primary/50"
        />
      )}

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={handleApprove}
          disabled={disabled}
          className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground transition-[filter] hover:brightness-110 disabled:opacity-60 cursor-pointer"
        >
          {loading ? (
            <RefreshCw className="size-4 animate-spin" />
          ) : (
            <Check className="size-4" />
          )}
          {dirty ? "Подтвердить изменения" : "Подтвердить"}
        </button>
        {!rejecting && (
          <button
            type="button"
            onClick={() => setEditing((v) => !v)}
            disabled={disabled}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-sm transition-colors hover:bg-muted/40 disabled:opacity-60 cursor-pointer"
          >
            <Pencil className="size-4" />
            {editing ? "Готово" : "Изменить"}
          </button>
        )}
        <button
          type="button"
          onClick={handleReject}
          disabled={disabled}
          className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-muted/40 disabled:opacity-60 cursor-pointer"
        >
          <X className="size-4" />
          {rejecting ? "Отправить" : "Отклонить"}
        </button>
      </div>
    </div>
  );
};

export default PlanApprovalCard;
