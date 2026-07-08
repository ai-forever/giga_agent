import React from "react";

import type { Accent, Composition } from "./types";
import { IssueCard } from "./IssueCard";
import { WidgetShell, EmptyState } from "./WidgetShell";

/**
 * Рендерер генеративной доски: композиция групп, собранная агентом в рантайме
 * (через push_ui_message), отрисованная теми же примитивами кита. В отличие от
 * статического Board, группы здесь именованные и с акцентами — это решение
 * агента, а не фиксированная разбивка по полю.
 */

const ACCENT_BORDER: Record<Accent, string> = {
  success: "border-emerald-500/50",
  info: "border-blue-500/50",
  warning: "border-amber-500/50",
  danger: "border-rose-500/50",
};

const ACCENT_DOT: Record<Accent, string> = {
  success: "bg-emerald-500",
  info: "bg-blue-500",
  warning: "bg-amber-500",
  danger: "bg-rose-500",
};

export const ComposedBoard: React.FC<{ composition: Composition }> = ({
  composition,
}) => {
  const groups = composition.groups ?? [];
  const total = groups.reduce((n, g) => n + (g.issues?.length ?? 0), 0);

  if (!total) {
    return (
      <WidgetShell>
        <EmptyState>Задачи не найдены</EmptyState>
      </WidgetShell>
    );
  }

  return (
    <WidgetShell>
      <div className="mb-1.5 px-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        {composition.title ?? "Доска"} · {total}
      </div>
      <div className="flex flex-col gap-2.5">
        {groups.map((g) => (
          <section
            key={g.label}
            className={`rounded-md border-l-2 pl-2 ${
              g.accent ? ACCENT_BORDER[g.accent] : "border-border/50"
            }`}
          >
            <div className="mb-1 flex items-center gap-1.5 px-0.5 text-[11px] font-medium text-muted-foreground">
              {g.accent && (
                <span
                  className={`size-1.5 rounded-full ${ACCENT_DOT[g.accent]}`}
                />
              )}
              {g.label} · {g.issues?.length ?? 0}
            </div>
            <div className="grid gap-1.5 sm:grid-cols-2">
              {(g.issues ?? []).map((it) => (
                <IssueCard key={it.key} issue={it} />
              ))}
            </div>
          </section>
        ))}
      </div>
    </WidgetShell>
  );
};
