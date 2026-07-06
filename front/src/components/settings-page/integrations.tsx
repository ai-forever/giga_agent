import React, { useCallback, useEffect, useState } from "react";
import { Plug, Trash2, Check, AlertTriangle } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { SecretInput } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { apiClient } from "@/lib/api-client";
import { resolveProviderIcon } from "@/lib/provider-icons";
import { API_AGENT_PREFIX } from "@/config.ts";
import { useUserInfo } from "@/components/providers/user-info-context";
import { useOAuthPopup } from "@/components/integrations/use-oauth-popup";

const INTEGRATIONS_URL = `${API_AGENT_PREFIX}/integrations`;

type ConnStatus = "not_connected" | "connected" | "needs_reauth";

interface ManualField {
  key: string;
  label: string;
  secret: boolean;
  placeholder?: string | null;
}

interface Provider {
  key: string;
  label: string;
  icon?: string | null;
  auth_kind: "oauth2" | "manual_token" | "both";
  status: ConnStatus;
  scope?: string | null;
  token_hint?: string | null;
  manual_fields: ManualField[];
}

const STATUS_META: Record<
  ConnStatus,
  { label: string; variant: "default" | "outline" | "destructive" }
> = {
  connected: { label: "Подключено", variant: "default" },
  needs_reauth: {
    label: "Нужна повторная авторизация",
    variant: "destructive",
  },
  not_connected: { label: "Не подключено", variant: "outline" },
};

export const IntegrationsSettings: React.FC = () => {
  const { refreshModules } = useUserInfo();
  const [providers, setProviders] = useState<Provider[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [manualInputs, setManualInputs] = useState<
    Record<string, Record<string, string>>
  >({});

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiClient.get<Provider[]>(INTEGRATIONS_URL);
      setProviders(data);
    } catch (e: any) {
      toast.error(e?.message || "Не удалось загрузить интеграции");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const openPopup = useOAuthPopup(
    "integration_auth_callback",
    (success, data) => {
      if (success) {
        toast.success("Авторизация прошла успешно");
        void load();
        refreshModules();
      } else {
        toast.error(`Авторизация не удалась: ${data?.error || "ошибка"}`);
      }
    },
  );

  const handleConnect = async (provider: Provider) => {
    setBusyKey(provider.key);
    try {
      const { authorization_url } = await apiClient.get<{
        authorization_url: string;
      }>(`${INTEGRATIONS_URL}/${provider.key}/oauth/start`);
      openPopup(authorization_url);
    } catch (e: any) {
      toast.error(e?.message || "Не удалось начать авторизацию");
    } finally {
      setBusyKey(null);
    }
  };

  const handleSaveManual = async (provider: Provider) => {
    setBusyKey(provider.key);
    try {
      await apiClient.post(`${INTEGRATIONS_URL}/${provider.key}/token`, {
        fields: manualInputs[provider.key] ?? {},
      });
      toast.success("Сохранено");
      setManualInputs((prev) => ({ ...prev, [provider.key]: {} }));
      await load();
      refreshModules();
    } catch (e: any) {
      toast.error(e?.message || "Не удалось сохранить токен");
    } finally {
      setBusyKey(null);
    }
  };

  const handleDisconnect = async (provider: Provider) => {
    setBusyKey(provider.key);
    try {
      await apiClient.delete(`${INTEGRATIONS_URL}/${provider.key}`);
      toast.success("Отключено");
      await load();
      refreshModules();
    } catch (e: any) {
      toast.error(e?.message || "Не удалось отключить");
    } finally {
      setBusyKey(null);
    }
  };

  return (
    <div className="space-y-4 max-w-[720px]">
      <div className="space-y-1">
        <h2 className="text-lg font-semibold">Интеграции</h2>
        <p className="text-sm text-muted-foreground">
          Подключите внешние сервисы через OAuth или вставьте токен вручную.
          Модули агента используют эти подключения.
        </p>
      </div>

      {loading ? (
        <div className="text-sm text-muted-foreground">Загрузка…</div>
      ) : providers.length === 0 ? (
        <div className="text-sm text-muted-foreground">
          Нет доступных интеграций.
        </div>
      ) : (
        <div className="space-y-3">
          {providers.map((p) => {
            const meta = STATUS_META[p.status];
            const isConnected = p.status === "connected";
            const showManual =
              (p.auth_kind === "manual_token" || p.auth_kind === "both") &&
              !isConnected;
            const showOAuth =
              (p.auth_kind === "oauth2" || p.auth_kind === "both") &&
              !isConnected;
            const busy = busyKey === p.key;
            return (
              <div
                key={p.key}
                className="rounded-lg border border-border p-4 space-y-3"
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2 min-w-0">
                    {p.icon ? (
                      <img
                        src={resolveProviderIcon(p.key, p.icon) ?? p.icon}
                        alt=""
                        className="w-5 h-5 rounded"
                        onError={(e) => {
                          (e.currentTarget as HTMLImageElement).style.display =
                            "none";
                        }}
                      />
                    ) : (
                      <Plug className="w-4 h-4" />
                    )}
                    <span className="font-medium truncate">{p.label}</span>
                    <Badge variant={meta.variant} className="ml-1">
                      {p.status === "needs_reauth" && (
                        <AlertTriangle className="w-3 h-3 mr-1" />
                      )}
                      {isConnected && <Check className="w-3 h-3 mr-1" />}
                      {meta.label}
                    </Badge>
                  </div>
                  {isConnected && (
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={busy}
                      onClick={() => handleDisconnect(p)}
                    >
                      <Trash2 className="w-4 h-4 mr-1" />
                      Отключить
                    </Button>
                  )}
                </div>

                {showOAuth && (
                  <Button
                    size="sm"
                    disabled={busy}
                    onClick={() => handleConnect(p)}
                  >
                    <Plug className="w-4 h-4 mr-1" />
                    Подключить
                  </Button>
                )}

                {showManual && (
                  <div className="space-y-2">
                    {p.manual_fields.map((f) => (
                      <SecretInput
                        key={f.key}
                        placeholder={f.placeholder || f.label}
                        value={manualInputs[p.key]?.[f.key] ?? ""}
                        onChange={(e) =>
                          setManualInputs((prev) => ({
                            ...prev,
                            [p.key]: {
                              ...(prev[p.key] ?? {}),
                              [f.key]: e.target.value,
                            },
                          }))
                        }
                      />
                    ))}
                    <Button
                      size="sm"
                      disabled={busy}
                      onClick={() => handleSaveManual(p)}
                    >
                      Сохранить
                    </Button>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default IntegrationsSettings;
