import React, { useMemo, useState } from "react";
import { Mail, MailOpen, Loader, ChevronDown, ChevronRight } from "lucide-react";
import type { Message } from "@langchain/langgraph-sdk";
import type { ToolCall } from "@langchain/core/messages/tool";
import { toast } from "sonner";

import { API_AGENT_PREFIX } from "../../config";
import { apiClient } from "../../lib/api-client";
import { WidgetShell, EmptyState } from "./kit";
import type { MailMessage, MailInboxPayload } from "./kit";

/**
 * GenUI-виджет входящих, маршрутизируемый по маркеру `widget:"mail_inbox"`
 * (provider-agnostic, как трекер/диск). Список писем; клик раскрывает тело
 * через REST `/{provider}/read` — без round-trip через модель. Отправка не
 * из виджета: mail_send остаётся за агентом (confirm-гейт на деструктив).
 */

const MailRow: React.FC<{ msg: MailMessage; provider: string; folder: string }> = ({
  msg,
  provider,
  folder,
}) => {
  const [open, setOpen] = useState(false);
  const [body, setBody] = useState<string | null>(msg.body ?? null);
  const [loading, setLoading] = useState(false);

  async function toggle() {
    const next = !open;
    setOpen(next);
    if (next && body == null && !loading) {
      setLoading(true);
      try {
        const data = await apiClient.get<MailMessage>(
          `${API_AGENT_PREFIX}/${provider}/read?folder=${encodeURIComponent(
            folder,
          )}&message_id=${encodeURIComponent(msg.id)}`,
          { showError: false },
        );
        setBody(data?.body ?? "(пустое письмо)");
      } catch {
        toast.error("Не удалось открыть письмо");
        setBody(null);
        setOpen(false);
      } finally {
        setLoading(false);
      }
    }
  }

  return (
    <div className="border-b border-border/40 last:border-0">
      <button
        type="button"
        onClick={toggle}
        className="flex w-full items-center gap-2 px-1.5 py-1.5 text-left text-sm hover:bg-muted/50"
      >
        {open ? (
          <ChevronDown size={13} className="shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRight size={13} className="shrink-0 text-muted-foreground" />
        )}
        {open ? (
          <MailOpen size={14} className="shrink-0 text-muted-foreground" />
        ) : (
          <Mail size={14} className="shrink-0 text-blue-500" />
        )}
        <span className="w-32 shrink-0 truncate text-xs text-muted-foreground">
          {msg.from || "—"}
        </span>
        <span className="min-w-0 flex-1 truncate font-medium">
          {msg.subject || "(без темы)"}
        </span>
        {msg.date && (
          <span className="shrink-0 text-[11px] text-muted-foreground/70">
            {msg.date}
          </span>
        )}
      </button>
      {open && (
        <div className="px-7 pb-2 pt-0.5">
          {loading ? (
            <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
              <Loader size={12} className="animate-spin" /> Загрузка…
            </span>
          ) : (
            <div className="whitespace-pre-wrap text-xs leading-relaxed text-muted-foreground">
              {body}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

const MailInbox: React.FC<{
  toolCall: ToolCall;
  resultMessage?: Message;
  isStreaming: boolean;
}> = ({ resultMessage, isStreaming }) => {
  const payload = useMemo<MailInboxPayload | null>(() => {
    if (!resultMessage) return null;
    try {
      const raw =
        typeof resultMessage.content === "string"
          ? JSON.parse(resultMessage.content)
          : resultMessage.content;
      const inner = (raw as any)?.data ?? raw;
      return inner?.widget === "mail_inbox" ? inner : null;
    } catch {
      return null;
    }
  }, [resultMessage]);

  if (!resultMessage) {
    return (
      <WidgetShell>
        <EmptyState loading={isStreaming}>Открываю почту…</EmptyState>
      </WidgetShell>
    );
  }
  if (!payload) {
    return (
      <WidgetShell>
        <EmptyState tone="error">Некорректный ответ почты</EmptyState>
      </WidgetShell>
    );
  }

  const messages = payload.messages ?? [];
  const provider = payload.provider || "yandex_mail";

  return (
    <WidgetShell>
      <div className="mb-1 px-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        {payload.folder || "INBOX"} · {messages.length}
      </div>
      {messages.length === 0 ? (
        <EmptyState>Писем нет</EmptyState>
      ) : (
        <div className="flex flex-col">
          {messages.map((m) => (
            <MailRow
              key={m.id}
              msg={m}
              provider={provider}
              folder={payload.folder || "INBOX"}
            />
          ))}
        </div>
      )}
    </WidgetShell>
  );
};

export default MailInbox;
