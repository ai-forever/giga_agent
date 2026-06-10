import React, { useMemo, useState } from "react";
import { ChevronDown, Loader, User, Flag, CircleDot } from "lucide-react";
import type { Message } from "@langchain/langgraph-sdk";
import type { ToolCall } from "@langchain/core/messages/tool";
import { toast } from "sonner";

import { API_AGENT_PREFIX } from "../../config";
import { apiClient } from "../../lib/api-client";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "../ui/dropdown-menu";

/**
 * GenUI-виджет «доска задач» для результатов Яндекс.Трекера.
 *
 * Рендерит ответ tracker_search_issues / tracker_get_issue как карточки.
 * Главная фича — смена статуса прямо из карточки: бейдж статуса открывает
 * меню доступных переходов (лениво подгружается из REST модуля) и исполняет
 * выбранный переход напрямую, без round-trip через модель. UI обновляется
 * оптимистично, с откатом на ошибке.
 */

interface TrackerIssue {
  key: string;
  summary?: string;
  status?: string;
  assignee?: string;
  queue?: string;
  priority?: string;
  updatedAt?: string;
}

interface Transition {
  id: string;
  display?: string;
  to?: string;
}

// Грубая раскраска бейджа по русскому/английскому display-имени статуса.
function statusTone(status?: string): string {
  const s = (status || "").toLowerCase();
  if (/(закры|решён|решен|done|closed|resolved|выполн)/.test(s))
    return "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border-emerald-500/30";
  if (/(работ|progress|review|тест)/.test(s))
    return "bg-blue-500/15 text-blue-600 dark:text-blue-400 border-blue-500/30";
  if (/(отмен|cancel|reject|отклон)/.test(s))
    return "bg-rose-500/15 text-rose-600 dark:text-rose-400 border-rose-500/30";
  return "bg-muted text-muted-foreground border-border/60";
}

const IssueCard: React.FC<{ issue: TrackerIssue }> = ({ issue }) => {
  // Локальный оптимистичный статус поверх пришедшего из результата тула.
  const [status, setStatus] = useState<string | undefined>(issue.status);
  const [transitions, setTransitions] = useState<Transition[] | null>(null);
  const [loading, setLoading] = useState(false); // подгрузка переходов
  const [busy, setBusy] = useState(false); // исполнение перехода

  const base = `${API_AGENT_PREFIX}/yandex_tracker/issues/${encodeURIComponent(
    issue.key,
  )}`;

  async function loadTransitions(open: boolean) {
    if (!open || transitions || loading) return;
    setLoading(true);
    try {
      const data = await apiClient.get<{ transitions: Transition[] }>(
        `${base}/transitions`,
        { showError: false },
      );
      setTransitions(data?.transitions ?? []);
    } catch {
      setTransitions([]);
      toast.error(`Не удалось получить статусы для ${issue.key}`);
    } finally {
      setLoading(false);
    }
  }

  async function applyTransition(t: Transition) {
    const prev = status;
    setBusy(true);
    setStatus(t.to || t.display || prev); // оптимистично
    try {
      const data = await apiClient.post<{ issue?: TrackerIssue }>(
        `${base}/transitions/${encodeURIComponent(t.id)}`,
        undefined,
        { showError: false },
      );
      setStatus(data?.issue?.status ?? t.to ?? t.display ?? prev);
      setTransitions(null); // список переходов изменился — перечитаем при след. открытии
      toast.success(`${issue.key}: статус изменён`);
    } catch {
      setStatus(prev); // откат
      toast.error(`Не удалось изменить статус ${issue.key}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-lg border border-border/50 bg-card/60 px-3 py-2.5 transition-colors hover:border-border">
      <div className="mb-1 flex items-center gap-2">
        <span className="font-mono text-[11px] font-medium text-muted-foreground">
          {issue.key}
        </span>
        {issue.queue && (
          <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
            {issue.queue}
          </span>
        )}
      </div>

      <div className="mb-2 text-sm font-medium leading-snug text-foreground">
        {issue.summary || "(без заголовка)"}
      </div>

      <div className="flex flex-wrap items-center gap-2 text-xs">
        <DropdownMenu onOpenChange={loadTransitions}>
          <DropdownMenuTrigger
            disabled={busy}
            className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-medium outline-none transition-opacity hover:opacity-80 disabled:opacity-50 ${statusTone(
              status,
            )}`}
          >
            {busy ? (
              <Loader size={11} className="animate-spin" />
            ) : (
              <CircleDot size={11} />
            )}
            {status || "—"}
            <ChevronDown size={11} className="opacity-60" />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="min-w-[180px]">
            {loading && (
              <div className="flex items-center gap-2 px-2 py-1.5 text-xs text-muted-foreground">
                <Loader size={12} className="animate-spin" /> Загрузка…
              </div>
            )}
            {!loading && transitions && transitions.length === 0 && (
              <div className="px-2 py-1.5 text-xs text-muted-foreground">
                Нет доступных переходов
              </div>
            )}
            {!loading &&
              transitions?.map((t) => (
                <DropdownMenuItem
                  key={t.id}
                  onSelect={() => applyTransition(t)}
                  className="text-xs"
                >
                  {t.display || t.to || t.id}
                  {t.to && (
                    <span className="ml-auto text-[10px] text-muted-foreground">
                      → {t.to}
                    </span>
                  )}
                </DropdownMenuItem>
              ))}
          </DropdownMenuContent>
        </DropdownMenu>

        {issue.assignee && (
          <span className="inline-flex items-center gap-1 text-muted-foreground">
            <User size={11} />
            {issue.assignee}
          </span>
        )}
        {issue.priority && (
          <span className="inline-flex items-center gap-1 text-muted-foreground">
            <Flag size={11} />
            {issue.priority}
          </span>
        )}
      </div>
    </div>
  );
};

const Shell: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div className="my-1 rounded-lg border border-border/50 bg-muted/15 p-2">
    {children}
  </div>
);

const IssueBoard: React.FC<{
  toolCall: ToolCall;
  resultMessage?: Message;
  isStreaming: boolean;
}> = ({ resultMessage, isStreaming }) => {
  const parsed = useMemo<{ issues: TrackerIssue[]; error?: string }>(() => {
    if (!resultMessage) return { issues: [] };
    let payload: any;
    try {
      payload =
        typeof resultMessage.content === "string"
          ? JSON.parse(resultMessage.content)
          : resultMessage.content;
    } catch {
      return { issues: [], error: undefined };
    }
    const inner = payload?.data ?? payload;
    if (inner?.error) return { issues: [], error: String(inner.error) };
    if (Array.isArray(inner?.issues))
      return { issues: inner.issues as TrackerIssue[] };
    if (inner?.key) return { issues: [inner as TrackerIssue] }; // get_issue
    return { issues: [] };
  }, [resultMessage]);

  if (!resultMessage) {
    return (
      <Shell>
        <div className="flex items-center gap-2 px-1 py-0.5 text-xs text-muted-foreground">
          {isStreaming && <Loader size={12} className="animate-spin" />}
          Ищу задачи в Трекере…
        </div>
      </Shell>
    );
  }

  if (parsed.error) {
    return (
      <Shell>
        <div className="px-1 py-0.5 text-xs text-rose-500">{parsed.error}</div>
      </Shell>
    );
  }

  if (!parsed.issues.length) {
    return (
      <Shell>
        <div className="px-1 py-0.5 text-xs text-muted-foreground">
          Задачи не найдены
        </div>
      </Shell>
    );
  }

  return (
    <Shell>
      <div className="mb-1.5 px-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        Задачи · {parsed.issues.length}
      </div>
      <div className="grid gap-1.5 sm:grid-cols-2">
        {parsed.issues.map((it) => (
          <IssueCard key={it.key} issue={it} />
        ))}
      </div>
    </Shell>
  );
};

export default IssueBoard;
