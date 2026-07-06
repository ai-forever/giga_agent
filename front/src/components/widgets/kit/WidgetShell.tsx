import React from "react";
import { Loader } from "lucide-react";

/** Общая «рамка» трекерного виджета (фон/бордер/паддинг). */
export const WidgetShell: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => (
  <div className="my-1 rounded-lg border border-border/50 bg-muted/15 p-2">
    {children}
  </div>
);

/** Пустые/загрузочные/ошибочные состояния виджета — единым стилем. */
export const EmptyState: React.FC<{
  tone?: "muted" | "error";
  loading?: boolean;
  children: React.ReactNode;
}> = ({ tone = "muted", loading = false, children }) => (
  <div
    className={`flex items-center gap-2 px-1 py-0.5 text-xs ${
      tone === "error" ? "text-rose-500" : "text-muted-foreground"
    }`}
  >
    {loading && <Loader size={12} className="animate-spin" />}
    {children}
  </div>
);
