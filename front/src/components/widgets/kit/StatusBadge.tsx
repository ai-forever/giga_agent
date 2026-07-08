import React, { useState } from "react";
import { ChevronDown, Loader, CircleDot } from "lucide-react";
import { toast } from "sonner";

import { API_AGENT_PREFIX } from "../../../config";
import { apiClient } from "../../../lib/api-client";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "../../ui/dropdown-menu";

interface Transition {
  id: string;
  display?: string;
  to?: string;
}

// Грубая раскраска бейджа по display-имени статуса (ru/en).
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

/**
 * Бейдж статуса с дропдауном переходов. Provider-agnostic: REST-база строится
 * из `provider` (= module_id), а не хардкодится под Яндекс. Любой трекер,
 * выставивший эндпоинты `/{provider}/issues/{key}/transitions`, работает здесь
 * без правок. Оптимистичный апдейт с откатом на ошибке.
 */
export const StatusBadge: React.FC<{
  provider: string;
  issueKey: string;
  status?: string;
}> = ({ provider, issueKey, status: initialStatus }) => {
  const [status, setStatus] = useState<string | undefined>(initialStatus);
  const [transitions, setTransitions] = useState<Transition[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);

  const base = `${API_AGENT_PREFIX}/${provider}/issues/${encodeURIComponent(
    issueKey,
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
      toast.error(`Не удалось получить статусы для ${issueKey}`);
    } finally {
      setLoading(false);
    }
  }

  async function applyTransition(t: Transition) {
    const prev = status;
    setBusy(true);
    setStatus(t.to || t.display || prev); // оптимистично
    try {
      const data = await apiClient.post<{ issue?: { status?: string } }>(
        `${base}/transitions/${encodeURIComponent(t.id)}`,
        undefined,
        { showError: false },
      );
      setStatus(data?.issue?.status ?? t.to ?? t.display ?? prev);
      setTransitions(null); // список переходов изменился — перечитаем при открытии
      toast.success(`${issueKey}: статус изменён`);
    } catch {
      setStatus(prev); // откат
      toast.error(`Не удалось изменить статус ${issueKey}`);
    } finally {
      setBusy(false);
    }
  }

  return (
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
  );
};
