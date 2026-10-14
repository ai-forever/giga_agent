import React, { useState } from "react";
import {
  AlertCircle,
  Check,
  ChevronDown,
  Copy,
  Loader2,
  Minimize2,
} from "lucide-react";
import { toast } from "sonner";

import TextMarkdown from "./attachments/TextMarkdown";

export interface ContextCompactionData {
  version: number;
  status?: "started" | "completed" | "failed";
  operation_id?: string | null;
  through_message_id?: string | null;
  source_digest?: string;
  reason: "auto" | "manual";
  input_tokens_before?: number | null;
  input_tokens_after?: number | null;
  context_window?: number | null;
  compacted_message_count?: number;
  retained_message_count?: number;
}

const formatTokens = (value: number) =>
  value >= 1000 ? `${(value / 1000).toFixed(1)}K` : String(value);

const ContextSummaryCard: React.FC<{
  summary: string;
  data: ContextCompactionData;
}> = ({ summary, data }) => {
  const [expanded, setExpanded] = useState(false);
  const [copied, setCopied] = useState(false);
  const status = data.status ?? "completed";

  if (status === "started") {
    return (
      <div className="rounded-xl border border-border/70 bg-muted/20 p-3 shadow-sm">
        <div className="flex items-center gap-2">
          <Loader2 className="size-4 animate-spin text-muted-foreground" />
          <div className="min-w-0 flex-1">
            <div className="text-sm font-medium">
              Суммаризация контекста запущена
            </div>
            <div className="text-xs text-muted-foreground">
              {data.reason === "manual" ? "Команда /compact" : "Автоматически"}
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (status === "failed") {
    return (
      <div className="rounded-xl border border-amber-300/70 bg-amber-50/60 p-3 shadow-sm dark:border-amber-700/50 dark:bg-amber-950/20">
        <div className="flex items-start gap-2">
          <AlertCircle className="mt-0.5 size-4 shrink-0 text-amber-700 dark:text-amber-400" />
          <div className="min-w-0 flex-1">
            <div className="text-sm font-medium">Суммаризация не выполнена</div>
            <div className="mt-1 text-sm text-muted-foreground">{summary}</div>
          </div>
        </div>
      </div>
    );
  }

  const copy = async () => {
    await navigator.clipboard.writeText(summary);
    setCopied(true);
    toast.success("Сводка скопирована");
    window.setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="rounded-xl border border-border/70 bg-muted/20 p-3 shadow-sm">
      <div className="flex items-center gap-2">
        <Minimize2 className="size-4 text-muted-foreground" />
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium">Контекст сокращён</div>
          <div className="text-xs text-muted-foreground">
            {data.reason === "manual" ? "Команда /compact" : "Автоматически"}
            {typeof data.input_tokens_before === "number"
              ? ` · ${formatTokens(data.input_tokens_before)} входных токенов`
              : ""}
            {typeof data.input_tokens_after === "number"
              ? ` -> ${formatTokens(data.input_tokens_after)}`
              : ""}
            {typeof data.compacted_message_count === "number" &&
            typeof data.retained_message_count === "number"
              ? ` · сокращено ${data.compacted_message_count}, сохранено ${data.retained_message_count} сообщений`
              : ""}
          </div>
        </div>
        <button
          type="button"
          onClick={() => void copy()}
          title="Копировать сводку"
          className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          {copied ? <Check className="size-4" /> : <Copy className="size-4" />}
        </button>
        <button
          type="button"
          aria-expanded={expanded}
          onClick={() => setExpanded((value) => !value)}
          className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          <ChevronDown
            className={`size-4 transition-transform ${expanded ? "rotate-180" : ""}`}
          />
        </button>
      </div>
      {expanded && (
        <div className="mt-3 border-t border-border/50 pt-3 text-sm [&_h1]:text-lg [&_h2]:text-base [&_h3]:text-sm">
          <TextMarkdown>{summary}</TextMarkdown>
        </div>
      )}
    </div>
  );
};

export default ContextSummaryCard;
