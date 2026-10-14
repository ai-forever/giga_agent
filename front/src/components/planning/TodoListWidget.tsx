import React, { useState } from "react";
import {
  Ban,
  Check,
  ChevronDown,
  ChevronUp,
  Circle,
  ListChecks,
  Loader,
} from "lucide-react";

import type { PlanTodo } from "../../interfaces";

const STATUS_LABELS: Record<PlanTodo["status"], string> = {
  pending: "Ожидает выполнения",
  in_progress: "Выполняется",
  completed: "Выполнено",
  cancelled: "Отменено",
};

const TodoStatusIcon: React.FC<{
  status: PlanTodo["status"];
  active: boolean;
}> = ({ status, active }) => {
  if (status === "completed") {
    return <Check className="size-4 text-emerald-500" aria-hidden />;
  }
  if (status === "cancelled") {
    return <Ban className="size-3.5 text-muted-foreground/60" aria-hidden />;
  }
  if (status === "in_progress") {
    return active ? (
      <Loader className="size-3.5 animate-spin text-blue-500" aria-hidden />
    ) : (
      <Circle className="size-3 fill-rose-500 text-rose-500" aria-hidden />
    );
  }
  return (
    <Circle
      className="size-3 fill-muted-foreground/40 text-muted-foreground/40"
      aria-hidden
    />
  );
};

interface TodoListWidgetProps {
  todos: PlanTodo[];
  active?: boolean;
  error?: boolean;
}

/** Полный серверный снимок рабочего списка, возвращённый `write_todo`. */
const TodoListWidget: React.FC<TodoListWidgetProps> = ({
  todos,
  active = false,
  error = false,
}) => {
  const [expanded, setExpanded] = useState(false);
  const completed = todos.filter(
    (todo) => todo.status === "completed" || todo.status === "cancelled",
  ).length;
  const progress = todos.length
    ? Math.round((completed / todos.length) * 100)
    : 0;
  const canToggle = !error;
  const header = (
    <>
      <ListChecks className="size-4 text-muted-foreground" aria-hidden />
      <h3 className="text-sm font-medium text-foreground">
        Задачи {todos.length}
      </h3>
      {!error && (
        <span className="ml-auto text-xs tabular-nums text-muted-foreground">
          {completed}/{todos.length}
        </span>
      )}
      {!error &&
        (expanded ? (
          <ChevronUp className="size-4 text-muted-foreground" aria-hidden />
        ) : (
          <ChevronDown className="size-4 text-muted-foreground" aria-hidden />
        ))}
    </>
  );

  return (
    <section
      className="mt-1 rounded-xl border border-border bg-muted/20 p-3"
      aria-label="Список задач"
    >
      {canToggle ? (
        <button
          type="button"
          className="flex w-full items-center gap-2 text-left"
          onClick={() => setExpanded((value) => !value)}
          aria-expanded={expanded}
        >
          {header}
        </button>
      ) : (
        <div className="flex items-center gap-2">{header}</div>
      )}
      {error && (
        <p className="mt-1 text-sm text-destructive">
          Не получилось поменять задачи.
        </p>
      )}
      {!expanded && !error && (
        <div
          className="mt-2.5 h-1 w-full overflow-hidden rounded-full bg-muted"
          role="progressbar"
          aria-label="Выполнение задач"
          aria-valuemin={0}
          aria-valuemax={todos.length}
          aria-valuenow={completed}
        >
          <div
            className="h-full rounded-full bg-emerald-500 transition-all duration-500"
            style={{ width: `${progress}%` }}
          />
        </div>
      )}
      {!error && (
        <div
          className={`grid transition-[grid-template-rows,opacity] duration-200 ease-out motion-reduce:transition-none ${
            expanded
              ? "mt-2.5 grid-rows-[1fr] opacity-100"
              : "grid-rows-[0fr] opacity-0"
          }`}
        >
          <div className="overflow-hidden">
            <div
              className="mb-2.5 h-1 w-full overflow-hidden rounded-full bg-muted"
              role="progressbar"
              aria-label="Выполнение задач"
              aria-valuemin={0}
              aria-valuemax={todos.length}
              aria-valuenow={completed}
            >
              <div
                className="h-full rounded-full bg-emerald-500 transition-all duration-500"
                style={{ width: `${progress}%` }}
              />
            </div>
            <ol className="flex flex-col gap-0.5">
              {todos.map((todo) => {
                const inProgress = todo.status === "in_progress";
                const completedTodo = todo.status === "completed";
                const cancelled = todo.status === "cancelled";

                return (
                  <li
                    key={todo.id}
                    className={`flex items-start gap-2.5 rounded-md px-2 py-1.5 text-sm ${
                      inProgress ? "bg-blue-500/10" : ""
                    }`}
                  >
                    <span className="mt-0.5 flex size-4 shrink-0 items-center justify-center">
                      <TodoStatusIcon status={todo.status} active={active} />
                      <span className="sr-only">
                        {STATUS_LABELS[todo.status]}
                      </span>
                    </span>
                    <div className="min-w-0 flex-1">
                      <div
                        className={
                          inProgress
                            ? "font-medium text-foreground"
                            : cancelled
                              ? "text-muted-foreground line-through decoration-muted-foreground/50"
                              : completedTodo
                                ? "text-muted-foreground"
                                : "text-foreground"
                        }
                      >
                        {todo.content}
                      </div>
                      {todo.note && (
                        <div className="mt-0.5 text-xs text-muted-foreground">
                          {todo.note}
                        </div>
                      )}
                    </div>
                  </li>
                );
              })}
            </ol>
          </div>
        </div>
      )}
    </section>
  );
};

export default TodoListWidget;
