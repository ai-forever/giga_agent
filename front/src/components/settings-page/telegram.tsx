import React, { useState, useEffect, useCallback } from "react";
import { Loader2, Trash2, Save, Bot } from "lucide-react";
import { toast } from "sonner";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { SecretInput } from "@/components/ui/input";
import { API_AGENT_PREFIX } from "@/config.ts";
import { apiClient } from "@/lib/api-client";
import { useConfirm } from "@/components/providers/confirm.tsx";

interface TelegramBotResponse {
  id: string;
  user_id: string;
  is_enabled: boolean;
  bot_username: string | null;
  created_at: string;
  updated_at: string;
}

interface TelegramBotStatus {
  configured: boolean;
  running: boolean;
  bot_username: string | null;
  is_enabled: boolean;
}

export const TelegramSettings: React.FC = () => {
  const [bot, setBot] = useState<TelegramBotResponse | null>(null);
  const [status, setStatus] = useState<TelegramBotStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [token, setToken] = useState("");
  const [isEnabled, setIsEnabled] = useState(true);
  const [isEditing, setIsEditing] = useState(false);
  const confirm = useConfirm();

  const loadBot = useCallback(async () => {
    try {
      setLoading(true);
      const [botData, statusData] = await Promise.all([
        apiClient.get<TelegramBotResponse | null>(
          `${API_AGENT_PREFIX}/telegram/bot`
        ),
        apiClient.get<TelegramBotStatus>(
          `${API_AGENT_PREFIX}/telegram/bot/status`
        ),
      ]);
      setBot(botData);
      setStatus(statusData);
      if (botData) {
        setIsEnabled(botData.is_enabled);
      }
    } catch {
      toast.error("Не удалось загрузить настройки Telegram");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadBot();
  }, [loadBot]);

  const handleCreate = async () => {
    if (!token.trim()) {
      toast.error("Введите токен бота");
      return;
    }
    setSaving(true);
    try {
      const created = await apiClient.post<TelegramBotResponse>(
        `${API_AGENT_PREFIX}/telegram/bot`,
        { bot_token: token.trim(), is_enabled: isEnabled }
      );
      setBot(created);
      setToken("");
      setIsEditing(false);
      toast.success(
        `Telegram бот @${created.bot_username || "bot"} подключён`
      );
      await loadBot();
    } catch (e: any) {
      const detail = e?.response?.data?.detail || "Ошибка при создании бота";
      toast.error(detail);
    } finally {
      setSaving(false);
    }
  };

  const handleUpdate = async () => {
    setSaving(true);
    try {
      const body: Record<string, any> = { is_enabled: isEnabled };
      if (token.trim()) {
        body.bot_token = token.trim();
      }
      const updated = await apiClient.patch<TelegramBotResponse>(
        `${API_AGENT_PREFIX}/telegram/bot`,
        body
      );
      setBot(updated);
      setToken("");
      setIsEditing(false);
      toast.success("Настройки обновлены");
      await loadBot();
    } catch (e: any) {
      const detail =
        e?.response?.data?.detail || "Ошибка при обновлении настроек";
      toast.error(detail);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    const ok = await confirm({
      description: "Удалить Telegram бота? Все привязки чатов будут потеряны.",
      variant: "destructive",
    });
    if (!ok) return;
    try {
      await apiClient.delete(`${API_AGENT_PREFIX}/telegram/bot`);
      setBot(null);
      setStatus(null);
      setToken("");
      setIsEditing(false);
      toast.success("Telegram бот удалён");
    } catch {
      toast.error("Ошибка при удалении бота");
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!bot && !isEditing) {
    return (
      <div className="space-y-6">
        <div className="flex items-center gap-2 text-muted-foreground mb-4">
          <Bot className="h-5 w-5" />
          <span>Telegram бот не настроен</span>
        </div>
        <p className="text-sm text-muted-foreground mb-4">
          Подключите Telegram бота, чтобы общаться с агентом через Telegram.
          Создайте бота через{" "}
          <a
            href="https://t.me/BotFather"
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary underline"
          >
            @BotFather
          </a>{" "}
          и вставьте токен ниже.
        </p>
        <Button onClick={() => setIsEditing(true)}>
          Подключить Telegram бота
        </Button>
      </div>
    );
  }

  if (isEditing && !bot) {
    return (
      <div className="space-y-4 max-w-lg">
        <div className="space-y-2">
          <Label>Токен бота (от @BotFather)</Label>
          <SecretInput
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
          />
        </div>
        <div className="flex items-center gap-2">
          <Switch checked={isEnabled} onCheckedChange={setIsEnabled} />
          <Label>Включить бота сразу</Label>
        </div>
        <div className="flex gap-2">
          <Button onClick={handleCreate} disabled={saving}>
            {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            <Save className="mr-2 h-4 w-4" />
            Сохранить
          </Button>
          <Button variant="outline" onClick={() => setIsEditing(false)}>
            Отмена
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-lg">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Bot className="h-5 w-5" />
          <div>
            <p className="font-medium">
              @{bot?.bot_username || "bot"}
            </p>
            <div className="flex gap-2 mt-1">
              {status?.running ? (
                <Badge variant="default" className="bg-green-600">
                  Работает
                </Badge>
              ) : (
                <Badge variant="secondary">Остановлен</Badge>
              )}
              {bot?.is_enabled ? (
                <Badge variant="outline">Включён</Badge>
              ) : (
                <Badge variant="destructive">Выключен</Badge>
              )}
            </div>
          </div>
        </div>
        <Button variant="ghost" size="icon" onClick={handleDelete}>
          <Trash2 className="h-4 w-4" />
        </Button>
      </div>

      <div className="border-t pt-4 space-y-4">
        <div className="flex items-center gap-2">
          <Switch
            checked={isEnabled}
            onCheckedChange={(val) => {
              setIsEnabled(val);
            }}
          />
          <Label>Бот включён</Label>
        </div>
        <div className="space-y-2">
          <Label>Новый токен (оставьте пустым чтобы не менять)</Label>
          <SecretInput
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder="Введите новый токен..."
          />
        </div>
        <Button onClick={handleUpdate} disabled={saving}>
          {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
          <Save className="mr-2 h-4 w-4" />
          Сохранить изменения
        </Button>
      </div>

      <div className="border-t pt-4">
        <p className="text-sm text-muted-foreground">
          Каждый чат в Telegram привязывается к отдельному треду агента.
          Память и MCP, настроенные в вашем профиле, доступны через Telegram.
        </p>
      </div>
    </div>
  );
};
