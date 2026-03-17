import React, { useCallback, useEffect, useState } from "react";
import { Loader2, Trash2 } from "lucide-react";
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
    </div>
  );
};

export default TelegramSettings;
