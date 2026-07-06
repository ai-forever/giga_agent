import React, { useMemo, useState } from "react";
import {
  Mail,
  MailOpen,
  Loader,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
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

/** Вёрстка письма в песочном iframe: скрипты и same-origin запрещены (защита от
 * XSS/трекеров), ссылки открываются в новой вкладке (base target + allow-popups). */
const MailHtmlFrame: React.FC<{ html: string }> = ({ html }) => {
  const srcDoc = useMemo(
    () =>
      '<!doctype html><html><head><meta charset="utf-8">' +
      '<base target="_blank">' +
      '<meta name="viewport" content="width=device-width, initial-scale=1">' +
      '</head><body style="margin:0;padding:8px;background:#fff;color:#111;' +
      "font-family:system-ui,-apple-system,sans-serif;font-size:13px;" +
      // Уменьшаем вёрстку письма до 60% (zoom корректно пересчитывает layout,
      // в отличие от transform:scale, который оставляет исходный бокс).
      'line-height:1.45;word-break:break-word;zoom:0.6">' +
      html +
      "</body></html>",
    [html],
  );
  return (
    <iframe
      title="Вёрстка письма"
      srcDoc={srcDoc}
      sandbox="allow-popups allow-popups-to-escape-sandbox"
      className="h-96 w-full rounded border border-border/40 bg-white"
    />
  );
};

const MailRow: React.FC<{
  msg: MailMessage;
  provider: string;
  folder: string;
}> = ({ msg, provider, folder }) => {
  const [open, setOpen] = useState(false);
  const [content, setContent] = useState<MailMessage | null>(
    msg.body != null || msg.html != null ? msg : null,
  );
  const [loading, setLoading] = useState(false);

  async function toggle() {
    const next = !open;
    setOpen(next);
    if (next && content == null && !loading) {
      setLoading(true);
      try {
        const data = await apiClient.get<MailMessage>(
          `${API_AGENT_PREFIX}/${provider}/read?folder=${encodeURIComponent(
            folder,
          )}&message_id=${encodeURIComponent(msg.id)}`,
          { showError: false },
        );
        setContent(data ?? { id: msg.id, body: "(пустое письмо)" });
      } catch {
        toast.error("Не удалось открыть письмо");
        setContent(null);
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
          ) : content?.html ? (
            <MailHtmlFrame html={content.html} />
          ) : (
            <div className="whitespace-pre-wrap text-xs leading-relaxed text-muted-foreground">
              {content?.body}
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
