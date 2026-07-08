import React, { useState } from "react";

import type { Issue } from "./types";
import { StatusBadge } from "./StatusBadge";
import { FieldRow } from "./FieldRow";

/**
 * Карточка задачи поверх нормализованного контракта Issue. Provider-agnostic:
 * статусом и переходами рулит StatusBadge через issue.provider; поля рисуются
 * из issue.fields, чип у ключа — из issue.tag, описание сворачивается.
 */
export const IssueCard: React.FC<{ issue: Issue }> = ({ issue }) => {
  const [descOpen, setDescOpen] = useState(false);
  const description = issue.description?.trim();
  const fields = issue.fields ?? [];

  return (
    <div className="rounded-lg border border-border/50 bg-card/60 px-3 py-2.5 transition-colors hover:border-border">
      <div className="mb-1 flex items-center gap-2">
        <span className="font-mono text-[11px] font-medium text-muted-foreground">
          {issue.key}
        </span>
        {issue.tag && (
          <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
            {issue.tag}
          </span>
        )}
      </div>

      <div className="mb-2 text-sm font-medium leading-snug text-foreground">
        {issue.title || "(без заголовка)"}
      </div>

      <div className="flex flex-wrap items-center gap-2 text-xs">
        <StatusBadge
          provider={issue.provider}
          issueKey={issue.key}
          status={issue.status}
        />
        {fields.map((f, i) => (
          <FieldRow key={f.label ?? `${f.icon}-${i}`} field={f} />
        ))}
      </div>

      {description && (
        <div className="mt-2 border-t border-border/40 pt-2">
          <div
            className={`whitespace-pre-wrap text-xs leading-relaxed text-muted-foreground ${
              descOpen ? "" : "line-clamp-3"
            }`}
          >
            {description}
          </div>
          {description.length > 160 && (
            <button
              type="button"
              onClick={() => setDescOpen((v) => !v)}
              className="mt-1 text-[11px] font-medium text-primary/80 hover:text-primary"
            >
              {descOpen ? "Свернуть" : "Показать описание"}
            </button>
          )}
        </div>
      )}
    </div>
  );
};
