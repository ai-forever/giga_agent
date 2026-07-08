import React, { useMemo } from "react";

import type { Issue } from "./types";
import { IssueCard } from "./IssueCard";
import { WidgetShell, EmptyState } from "./WidgetShell";

/** Значение, по которому группируем (status или label поля). */
function groupValue(issue: Issue, groupBy: string): string {
  if (groupBy === "status") return issue.status || "—";
  const f = (issue.fields ?? []).find((x) => x.label === groupBy);
  return f?.value || "—";
}

const Grid: React.FC<{ issues: Issue[] }> = ({ issues }) => (
  <div className="grid gap-1.5 sm:grid-cols-2">
    {issues.map((it) => (
      <IssueCard key={it.key} issue={it} />
    ))}
  </div>
);

/**
 * Доска задач поверх нормализованного контракта. По умолчанию — плоская сетка
 * (поведение совпадает со старым IssueBoard). С `groupBy` рендерит секции по
 * статусу/полю. Базис для kanban-режима в будущем (тот же IssueCard-кит).
 */
export const Board: React.FC<{
  issues: Issue[];
  title?: string;
  groupBy?: string;
  loading?: boolean;
  error?: string;
}> = ({ issues, title, groupBy, loading, error }) => {
  const groups = useMemo(() => {
    if (!groupBy) return null;
    const map = new Map<string, Issue[]>();
    for (const it of issues) {
      const k = groupValue(it, groupBy);
      (map.get(k) ?? map.set(k, []).get(k)!).push(it);
    }
    return [...map.entries()];
  }, [issues, groupBy]);

  if (loading) {
    return (
      <WidgetShell>
        <EmptyState loading>Загрузка задач…</EmptyState>
      </WidgetShell>
    );
  }
  if (error) {
    return (
      <WidgetShell>
        <EmptyState tone="error">{error}</EmptyState>
      </WidgetShell>
    );
  }
  if (!issues.length) {
    return (
      <WidgetShell>
        <EmptyState>Задачи не найдены</EmptyState>
      </WidgetShell>
    );
  }

  return (
    <WidgetShell>
      <div className="mb-1.5 px-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        {title ?? "Задачи"} · {issues.length}
      </div>
      {groups ? (
        <div className="flex flex-col gap-2">
          {groups.map(([name, items]) => (
            <div key={name}>
              <div className="mb-1 px-1 text-[11px] font-medium text-muted-foreground/80">
                {name} · {items.length}
              </div>
              <Grid issues={items} />
            </div>
          ))}
        </div>
      ) : (
        <Grid issues={issues} />
      )}
    </WidgetShell>
  );
};
