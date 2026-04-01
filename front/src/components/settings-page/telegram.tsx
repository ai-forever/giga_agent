import React, { useCallback, useEffect, useState } from "react";
import { Check, Loader2, Trash2, X, UserCheck, UserX } from "lucide-react";
import { toast } from "sonner";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { API_AGENT_PREFIX } from "@/config.ts";
import { apiClient } from "@/lib/api-client";
import { useConfirm } from "@/components/providers/confirm.tsx";

interface BotStatus {
  configured: boolean;
  running: boolean;
  bot_username?: string;
  is_enabled?: boolean;
}

interface BotResponse {
  id: string;
  bot_token: string;
  bot_username: string | null;
  is_enabled: boolean;
  user_id: string;
  created_at: string;
  updated_at: string;
}

interface TelegramContactItem {
  id: string;
  bot_id: string;
  telegram_chat_id: number;
  telegram_chat_type: string | null;
  telegram_chat_title: string | null;
  telegram_username: string | null;
  telegram_first_name: string | null;
  telegram_last_name: string | null;
  is_approved: boolean;
  created_at: string;
  updated_at: string;
}

const ContactsList: React.FC<{ configured: boolean }> = ({ configured }) => {
  const confirm = useConfirm();
  const [contacts, setContacts] = useState<TelegramContactItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [updatingKey, setUpdatingKey] = useState<string | null>(null);

  const fetchContacts = useCallback(async () => {
    if (!configured) return;
    setLoading(true);
    try {
      const data = await apiClient.get<TelegramContactItem[]>(
        `${API_AGENT_PREFIX}/telegram/contacts`,
      );
      setContacts(data);
    } catch {
      /* handled globally */
    } finally {
      setLoading(false);
    }
  }, [configured]);

  useEffect(() => {
    fetchContacts();
    const interval = setInterval(fetchContacts, 5000);
    return () => clearInterval(interval);
  }, [fetchContacts]);

  const handleApprove = async (chatId: number, approve: boolean) => {
    const actionKey = `approve:${chatId}`;
    setUpdatingKey(actionKey);
    try {
      await apiClient.patch<TelegramContactItem>(
        `${API_AGENT_PREFIX}/telegram/contacts/by-chat/${chatId}`,
        { is_approved: approve },
      );
      toast.success(approve ? "Контакт подтверждён" : "Доступ отозван");
      fetchContacts();
    } catch {
      /* handled globally */
    } finally {
      setUpdatingKey(null);
    }
  };

  const handleDelete = async (id: string) => {
    if (
      !(await confirm({
        description: "Удалить этот контакт? Пользователю придётся написать боту заново.",
        variant: "destructive",
      }))
    )
      return;
    const actionKey = `delete:${id}`;
    setUpdatingKey(actionKey);
    try {
      await apiClient.delete(`${API_AGENT_PREFIX}/telegram/contacts/${id}`);
      toast.success("Контакт удалён");
      fetchContacts();
    } catch {
      /* handled globally */
    } finally {
      setUpdatingKey(null);
    }
  };

  if (!configured) return null;

  const pending = contacts.filter((c) => !c.is_approved);
  const approved = contacts.filter((c) => c.is_approved);

  const contactName = (c: TelegramContactItem) => {
    if (c.telegram_chat_type && c.telegram_chat_type !== "private") {
      if (c.telegram_chat_title) return c.telegram_chat_title;
      if (c.telegram_username) return `@${c.telegram_username}`;
      return `chat ${c.telegram_chat_id}`;
    }
    const parts: string[] = [];
    if (c.telegram_first_name) parts.push(c.telegram_first_name);
    if (c.telegram_last_name) parts.push(c.telegram_last_name);
    if (parts.length) return parts.join(" ");
    if (c.telegram_username) return `@${c.telegram_username}`;
    return `chat ${c.telegram_chat_id}`;
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-4 text-muted-foreground text-sm">
        <Loader2 className="size-4 animate-spin mr-2" />
        Загрузка контактов...
      </div>
    );
  }

  if (contacts.length === 0) {
    return (
      <p className="text-sm text-muted-foreground py-2">
        Контактов пока нет. Они появятся, когда кто-то напишет вашему боту.
      </p>
    );
  }

  const renderContact = (c: TelegramContactItem) => (
    <div
      key={c.id}
      className="flex items-center gap-3 p-3 border border-border rounded-lg bg-card"
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-medium truncate">{contactName(c)}</span>
          {c.telegram_username && (
            <span className="text-muted-foreground text-xs">
              @{c.telegram_username}
            </span>
          )}
          <Badge variant={c.is_approved ? "default" : "secondary"}>
            {c.is_approved ? "Подтверждён" : "Ожидает"}
          </Badge>
        </div>
        <div className="text-xs text-muted-foreground mt-1">
          chat_id: {c.telegram_chat_id}
          {c.telegram_chat_type ? ` • ${c.telegram_chat_type}` : ""}
        </div>
      </div>
      <div className="flex items-center gap-1">
        {!c.is_approved ? (
          <Button
            size="sm"
            variant="default"
            disabled={updatingKey === `approve:${c.telegram_chat_id}`}
            onClick={() => handleApprove(c.telegram_chat_id, true)}
            title="Подтвердить"
          >
            {updatingKey === `approve:${c.telegram_chat_id}` ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <>
                <Check className="size-4 mr-1" />
                Подтвердить
              </>
            )}
          </Button>
        ) : (
          <Button
            size="sm"
            variant="outline"
            disabled={updatingKey === `approve:${c.telegram_chat_id}`}
            onClick={() => handleApprove(c.telegram_chat_id, false)}
            title="Отозвать доступ"
          >
            {updatingKey === `approve:${c.telegram_chat_id}` ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <>
                <X className="size-4 mr-1" />
                Отозвать
              </>
            )}
          </Button>
        )}
        <Button
          size="icon"
          variant="ghost"
          disabled={updatingKey === `delete:${c.id}`}
          onClick={() => handleDelete(c.id)}
          title="Удалить"
        >
          <Trash2 className="size-4 text-destructive" />
        </Button>
      </div>
    </div>
  );

  return (
    <div className="space-y-3">
      {pending.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-sm font-medium text-amber-600 dark:text-amber-400">
            <UserX className="size-4" />
            Ожидают подтверждения ({pending.length})
          </div>
          {pending.map(renderContact)}
        </div>
      )}
      {approved.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-sm font-medium text-green-600 dark:text-green-400">
            <UserCheck className="size-4" />
            Подтверждённые ({approved.length})
          </div>
          {approved.map(renderContact)}
        </div>
      )}
    </div>
  );
};

export const TelegramSettings: React.FC = () => {
  const confirm = useConfirm();
  const [status, setStatus] = useState<BotStatus | null>(null);
  const [botToken, setBotToken] = useState("");
  const [isEnabled, setIsEnabled] = useState(true);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const fetchStatus = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiClient.get<BotStatus>(
        `${API_AGENT_PREFIX}/telegram/bot/status`,
      );
      setStatus(data);
      if (data.is_enabled !== undefined) {
        setIsEnabled(data.is_enabled);
      }
    } catch {
      // handled globally
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  const handleCreate = async () => {
    if (!botToken.trim()) {
      toast.error("Введите токен бота");
      return;
    }
    setSaving(true);
    try {
      await apiClient.post<BotResponse>(
        `${API_AGENT_PREFIX}/telegram/bot`,
        { bot_token: botToken.trim(), is_enabled: isEnabled },
      );
      toast.success("Telegram бот настроен");
      setBotToken("");
      fetchStatus();
    } catch {
      // handled globally
    } finally {
      setSaving(false);
    }
  };

  const handleUpdate = async () => {
    setSaving(true);
    try {
      const payload: Record<string, unknown> = { is_enabled: isEnabled };
      if (botToken.trim()) {
        payload.bot_token = botToken.trim();
      }
      await apiClient.patch<BotResponse>(
        `${API_AGENT_PREFIX}/telegram/bot`,
        payload,
      );
      toast.success("Настройки обновлены");
      setBotToken("");
      fetchStatus();
    } catch {
      // handled globally
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (
      !(await confirm({
        description: "Вы уверены, что хотите удалить Telegram бота?",
        variant: "destructive",
      }))
    )
      return;

    setDeleting(true);
    try {
      await apiClient.delete(`${API_AGENT_PREFIX}/telegram/bot`);
      toast.success("Telegram бот удален");
      setStatus({ configured: false, running: false });
      setBotToken("");
      setIsEnabled(true);
    } catch {
      // handled globally
    } finally {
      setDeleting(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-8 text-muted-foreground">
        <Loader2 className="size-4 animate-spin mr-2" />
        Загрузка...
      </div>
    );
  }

  const isConfigured = status?.configured ?? false;

  return (
    <div className="space-y-6">
      <div>
        <h3 className="font-medium">Telegram</h3>
        <p className="text-sm text-muted-foreground mt-1">
          Подключение Telegram бота к агенту
        </p>
      </div>

      {isConfigured && (
        <div className="flex items-center gap-3 p-4 border border-border rounded-lg bg-card">
          <div className="flex-1">
            <div className="flex items-center gap-2">
              <span className="font-medium">
                @{status?.bot_username || "—"}
              </span>
              <Badge variant={status?.running ? "default" : "secondary"}>
                {status?.running ? "Запущен" : "Остановлен"}
              </Badge>
            </div>
          </div>
          <Button
            variant="ghost"
            size="icon"
            onClick={handleDelete}
            disabled={deleting || saving}
          >
            <Trash2 className="size-4 text-destructive" />
          </Button>
        </div>
      )}

      <div className="space-y-4 border border-border rounded-lg p-4 bg-muted/20">
        <div className="space-y-1.5">
          <Label htmlFor="bot-token">
            Токен бота{" "}
            {!isConfigured && <span className="text-destructive">*</span>}
            {isConfigured && (
              <span className="text-muted-foreground text-xs font-normal">
                (оставьте пустым, чтобы не менять)
              </span>
            )}
          </Label>
          <Input
            id="bot-token"
            type="password"
            placeholder="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
            value={botToken}
            onChange={(e) => setBotToken(e.target.value)}
            disabled={saving}
          />
        </div>

        <div className="flex items-center justify-between">
          <Label htmlFor="bot-enabled">Включен</Label>
          <Switch
            id="bot-enabled"
            checked={isEnabled}
            onCheckedChange={setIsEnabled}
            disabled={saving}
          />
        </div>

        <div className="flex gap-2 pt-2">
          <Button
            onClick={isConfigured ? handleUpdate : handleCreate}
            disabled={saving || (!isConfigured && !botToken.trim())}
          >
            {saving ? (
              <>
                <Loader2 className="size-4 animate-spin mr-2" />
                Сохранение...
              </>
            ) : isConfigured ? (
              "Сохранить"
            ) : (
              "Подключить"
            )}
          </Button>
        </div>
      </div>

      {isConfigured && (
        <div className="space-y-3">
          <div>
            <h3 className="font-medium">Контакты</h3>
            <p className="text-sm text-muted-foreground mt-1">
              Пользователи, которые написали вашему боту. Подтвердите контакт,
              чтобы разрешить общение.
            </p>
          </div>
          <ContactsList configured={isConfigured} />
        </div>
      )}
    </div>
  );
};

export default TelegramSettings;
