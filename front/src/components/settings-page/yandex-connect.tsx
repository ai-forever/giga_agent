import React, { useCallback, useEffect, useRef, useState } from "react";
import { HardDrive, ListTodo, Loader2, CheckCircle2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { API_AGENT_PREFIX } from "@/config.ts";
import { apiClient } from "@/lib/api-client";

type YandexModuleId = "yandex_disk" | "yandex_tracker";

interface OAuthStatus {
  configured: boolean;
  callback_available: boolean;
  connected: Record<string, boolean>;
}

interface StartResponse {
  authorize_url: string;
  flow: "callback" | "code";
}

const MODULES: { id: YandexModuleId; label: string; icon: React.ReactNode }[] = [
  {
    id: "yandex_disk",
    label: "Яндекс.Диск",
    icon: <HardDrive className="size-4" />,
  },
  {
    id: "yandex_tracker",
    label: "Яндекс.Трекер",
    icon: <ListTodo className="size-4" />,
  },
];

interface Props {
  /** Вызывается после успешного подключения/отключения, чтобы родитель
   * перечитал профиль (доступность модулей и маскированные секреты). */
  onChanged?: () => void | Promise<void>;
}

export const YandexConnect: React.FC<Props> = ({ onChanged }) => {
  const [status, setStatus] = useState<OAuthStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<YandexModuleId | null>(null);
  const [error, setError] = useState<string>("");
  // Состояние copy-paste флоу (когда server-callback недоступен).
  const [codeFlow, setCodeFlow] = useState<YandexModuleId | null>(null);
  const [codeValue, setCodeValue] = useState("");
  const popupRef = useRef<Window | null>(null);

  const fetchStatus = useCallback(async () => {
    try {
      const data = await apiClient.get<OAuthStatus>(
        `${API_AGENT_PREFIX}/yandex_oauth/status`,
      );
      setStatus(data);
    } catch {
      setStatus(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchStatus();
  }, [fetchStatus]);

  // Слушаем postMessage из popup-окна callback'а.
  useEffect(() => {
    const handler = (event: MessageEvent) => {
      const data = event.data;
      if (!data || data.type !== "yandex_oauth") return;
      setBusy(null);
      if (data.status === "connected") {
        void fetchStatus();
        void onChanged?.();
      } else {
        setError("Не удалось подключить аккаунт Яндекса. Попробуйте ещё раз.");
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, [fetchStatus, onChanged]);

  const connect = useCallback(
    async (moduleId: YandexModuleId) => {
      setError("");
      setBusy(moduleId);
      try {
        const res = await apiClient.get<StartResponse>(
          `${API_AGENT_PREFIX}/yandex_oauth/start?module=${moduleId}`,
        );
        if (res.flow === "callback") {
          popupRef.current = window.open(
            res.authorize_url,
            "yandex_oauth",
            "width=720,height=720",
          );
          // Дальше ждём postMessage из callback'а (см. effect выше).
        } else {
          // Copy-paste: открываем согласие в новой вкладке, показываем поле кода.
          window.open(res.authorize_url, "_blank", "noopener");
          setCodeFlow(moduleId);
          setCodeValue("");
          setBusy(null);
        }
      } catch (e) {
        setBusy(null);
        setError(
          e instanceof Error ? e.message : "Не удалось начать подключение.",
        );
      }
    },
    [],
  );

  const submitCode = useCallback(
    async (moduleId: YandexModuleId) => {
      const code = codeValue.trim();
      if (!code) return;
      setBusy(moduleId);
      setError("");
      try {
        await apiClient.post(`${API_AGENT_PREFIX}/yandex_oauth/exchange`, {
          module: moduleId,
          code,
        });
        setCodeFlow(null);
        setCodeValue("");
        await fetchStatus();
        await onChanged?.();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Неверный код подтверждения.");
      } finally {
        setBusy(null);
      }
    },
    [codeValue, fetchStatus, onChanged],
  );

  const disconnect = useCallback(
    async (moduleId: YandexModuleId) => {
      setBusy(moduleId);
      setError("");
      try {
        await apiClient.post(`${API_AGENT_PREFIX}/yandex_oauth/disconnect`, {
          module: moduleId,
        });
        await fetchStatus();
        await onChanged?.();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Не удалось отключить.");
      } finally {
        setBusy(null);
      }
    },
    [fetchStatus, onChanged],
  );

  if (loading) return null;
  // Если на сервере не настроено приложение Яндекса — секцию не показываем,
  // пользователь работает на ручных токенах ниже.
  if (!status?.configured) return null;

  return (
    <section className="space-y-3">
      <div>
        <h3 className="font-medium text-sm">Подключение Яндекса</h3>
        <p className="text-sm text-muted-foreground">
          Авторизуйтесь в Яндексе — токен сохранится и будет обновляться
          автоматически. Альтернатива ручному вводу ключей ниже.
        </p>
      </div>

      {error && (
        <div className="text-sm text-destructive bg-destructive/10 rounded-md px-3 py-2">
          {error}
        </div>
      )}

      <div className="space-y-3">
        {MODULES.map((mod) => {
          const connected = !!status.connected[mod.id];
          const isBusy = busy === mod.id;
          const inCodeFlow = codeFlow === mod.id;
          return (
            <div
              key={mod.id}
              className="border rounded-lg p-3 bg-muted/40 space-y-3"
            >
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-2 text-sm font-medium">
                  {mod.icon}
                  {mod.label}
                  {connected && (
                    <span className="flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-400">
                      <CheckCircle2 className="size-3.5" />
                      Подключено
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  {connected ? (
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={isBusy}
                      onClick={() => disconnect(mod.id)}
                    >
                      {isBusy && (
                        <Loader2 className="size-3.5 animate-spin mr-1" />
                      )}
                      Отключить
                    </Button>
                  ) : (
                    <Button
                      size="sm"
                      disabled={isBusy}
                      onClick={() => connect(mod.id)}
                    >
                      {isBusy && (
                        <Loader2 className="size-3.5 animate-spin mr-1" />
                      )}
                      Подключить
                    </Button>
                  )}
                </div>
              </div>

              {inCodeFlow && !connected && (
                <div className="space-y-2 border-t pt-3">
                  <Label htmlFor={`yandex-code-${mod.id}`} className="text-xs">
                    Вставьте код подтверждения со страницы Яндекса
                  </Label>
                  <div className="flex gap-2">
                    <Input
                      id={`yandex-code-${mod.id}`}
                      value={codeValue}
                      placeholder="Например, 1234567"
                      onChange={(e) => setCodeValue(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") void submitCode(mod.id);
                      }}
                    />
                    <Button
                      size="sm"
                      disabled={isBusy || !codeValue.trim()}
                      onClick={() => submitCode(mod.id)}
                    >
                      Готово
                    </Button>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
};
