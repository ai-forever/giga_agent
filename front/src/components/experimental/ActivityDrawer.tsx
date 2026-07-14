import React, { useMemo } from "react";
import { X, Check, Loader2, AlertCircle, Hammer } from "lucide-react";
import type { Activity, ActivityItem } from "@/interfaces";
import { TOOL_MAP } from "@/config";
import { formatDuration } from "./format";
import { useNowSeconds } from "./useNow";

interface ActivityDrawerProps {
  open: boolean;
  activity: Activity | null;
  onClose: () => void;
}

const toolLabel = (name: string): string =>
  (TOOL_MAP as Record<string, string>)[name] ?? name;

const StatusRow: React.FC<{ text: string }> = ({ text }) => (
  <div className="px-3 py-1.5 text-sm text-muted-foreground whitespace-pre-wrap break-words">
    {text}
  </div>
);

const ToolRow: React.FC<{
  item: Extract<ActivityItem, { type: "tool" }>;
}> = ({ item }) => {
  const running = item.status === "running" || item.ts_end == null;
  const error = item.status === "error";
  const duration =
    item.ts_end != null ? formatDuration(item.ts_end - item.ts) : null;
  return (
    <div className="flex items-center gap-2.5 px-3 py-2 rounded-lg hover:bg-accent/50">
      <Hammer size={15} className="flex-shrink-0 text-muted-foreground" />
      <span className="text-sm text-foreground flex-1 min-w-0 truncate">
        {toolLabel(item.name)}
      </span>
      {duration && (
        <span className="text-xs text-muted-foreground flex-shrink-0">
          {duration}
        </span>
      )}
      {running ? (
        <Loader2
          size={14}
          className="flex-shrink-0 animate-spin text-muted-foreground"
        />
      ) : error ? (
        <AlertCircle size={14} className="flex-shrink-0 text-destructive" />
      ) : (
        <Check size={14} className="flex-shrink-0 text-emerald-500" />
      )}
    </div>
  );
};

const ActivityDrawer: React.FC<ActivityDrawerProps> = ({
  open,
  activity,
  onClose,
}) => {
  const items = useMemo(
    () => [...(activity?.items ?? [])].sort((a, b) => a.ts - b.ts),
    [activity],
  );
  const running = activity != null && activity.finished_at == null;
  const now = useNowSeconds(open && running);

  let headerDuration: string | null = null;
  if (activity?.started_at != null) {
    const end = activity.finished_at ?? now;
    headerDuration = formatDuration(end - activity.started_at);
  }

  return (
    <>
      {open && (
        // Push-панель на десктопе не затемняет сдвинутый контент; бэкдроп нужен
        // только на узких экранах (там drawer перекрывает), чтобы закрыть тапом.
        <div
          className="fixed inset-0 z-[70] bg-black/20 min-[900px]:hidden"
          onClick={onClose}
          aria-hidden
        />
      )}
      <aside
        className={[
          "fixed top-0 right-0 bottom-0 z-[71] w-full max-w-[420px] bg-card border-l border-border shadow-lg transition-transform duration-200 ease-out flex flex-col",
          open ? "translate-x-0" : "translate-x-full",
        ].join(" ")}
        aria-hidden={!open}
      >
        <header className="flex items-center justify-between p-4 border-b border-border">
          <h3 className="text-base font-semibold">
            Активность{headerDuration ? ` · ${headerDuration}` : ""}
          </h3>
          <button
            type="button"
            onClick={onClose}
            title="Закрыть"
            className="p-1 rounded hover:bg-accent cursor-pointer"
          >
            <X size={18} />
          </button>
        </header>
        <div className="flex-1 overflow-y-auto p-2 space-y-0.5">
          {items.length === 0 ? (
            <div className="p-3 text-sm text-muted-foreground">
              {running ? "Собираю действия…" : "Нет активности"}
            </div>
          ) : (
            items.map((it, i) =>
              it.type === "tool" ? (
                <ToolRow key={it.id ?? i} item={it} />
              ) : (
                <StatusRow key={`s-${i}`} text={it.text} />
              ),
            )
          )}
        </div>
      </aside>
    </>
  );
};

export default ActivityDrawer;
