import React, { useEffect, useRef, useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  FileCog,
  Plug,
  RefreshCw,
  ShieldCheck,
  Trash2,
  Wrench,
} from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import { API_AGENT_PREFIX, RUNTIME_LOCAL } from "@/config.ts";
import { apiClient } from "@/lib/api-client";
import { useUserInfo } from "@/components/providers/user-info-context";
import { useOAuthPopup } from "@/components/integrations/use-oauth-popup";
import ConnectorIcon from "./connector-icon";
import type { ModuleCatalogEntry, ToolInfo, UnifiedServer } from "./types";
import { iconForConnector } from "./types";
import type { UseConnectorsResult } from "./use-connectors";

const INTEGRATIONS_URL = `${API_AGENT_PREFIX}/integrations`;

interface ConnectedTabProps {
  api: UseConnectorsResult;
  // Карточка, к которой нужно проскроллить и подсветить (db:<id> | module:<module_id>).
  highlightId: string | null;
}

const NEEDS_AUTH_BADGE = (
  <Badge variant="outline" className="border-amber-500/40 text-amber-500">
    нужна авторизация
  </Badge>
);

const ConnectorsConnectedTab: React.FC<ConnectedTabProps> = ({
  api,
  highlightId,
}) => {
  const {
    connectors,
    catalog,
    moduleCatalog,
    reloadCatalog,
    loading,
    busyId,
    toggleActive,
    remove,
    test,
    refresh,
    authorize,
    fetchTools,
    openLocalConfig,
  } = api;
  const { toggleModule, enabledModules, refreshModules } = useUserInfo();
  const [moduleBusy, setModuleBusy] = useState<string | null>(null);
  const connectedModules = moduleCatalog.filter(
    (m) => m.status !== "not_connected",
  );

  const highlightRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!highlightId) return;
    // Даём карточкам отрендериться после переключения вкладки.
    const t = setTimeout(() => {
      highlightRef.current?.scrollIntoView({
        behavior: "smooth",
        block: "center",
      });
    }, 100);
    return () => clearTimeout(t);
  }, [highlightId, connectors.length, connectedModules.length]);

  const cardClass = (id: string) =>
    cn(
      "rounded-md border bg-card p-3 flex flex-col gap-2 transition-shadow",
      highlightId === id && "ring-2 ring-primary",
    );
  const cardRef = (id: string) =>
    highlightId === id ? highlightRef : undefined;

  // module_id модуля, для которого сейчас идёт OAuth в popup'е.
  const pendingModuleRef = useRef<string | null>(null);
  const openModuleOAuth = useOAuthPopup(
    "integration_auth_callback",
    (success) => {
      pendingModuleRef.current = null;
      if (success) {
        toast.success("Авторизация прошла успешно");
        void reloadCatalog();
        refreshModules();
      } else {
        toast.error("Авторизация не удалась");
      }
    },
  );

  const authorizeModule = async (m: ModuleCatalogEntry) => {
    setModuleBusy(m.provider_key);
    try {
      const { authorization_url } = await apiClient.get<{
        authorization_url: string;
      }>(`${INTEGRATIONS_URL}/${m.provider_key}/oauth/start`);
      pendingModuleRef.current = m.module_id;
      openModuleOAuth(authorization_url);
    } catch (e: any) {
      toast.error(e?.message || "Не удалось начать авторизацию");
    } finally {
      setModuleBusy(null);
    }
  };

  const disconnectModule = async (providerKey: string) => {
    setModuleBusy(providerKey);
    try {
      await apiClient.delete(`${INTEGRATIONS_URL}/${providerKey}`);
      await reloadCatalog();
      refreshModules();
      toast.success("Отключено");
    } catch (e: any) {
      toast.error(e?.message || "Не удалось отключить");
    } finally {
      setModuleBusy(null);
    }
  };

  // key -> tools | "loading"
  const [toolsByKey, setToolsByKey] = useState<
    Record<string, ToolInfo[] | "loading">
  >({});

  const toggleTools = async (server: UnifiedServer) => {
    const existing = toolsByKey[server.key];
    if (existing) {
      setToolsByKey((prev) => {
        const next = { ...prev };
        delete next[server.key];
        return next;
      });
      return;
    }
    setToolsByKey((prev) => ({ ...prev, [server.key]: "loading" }));
    try {
      const tools = await fetchTools(server.key);
      setToolsByKey((prev) => ({ ...prev, [server.key]: tools }));
    } catch (e: any) {
      setToolsByKey((prev) => {
        const next = { ...prev };
        delete next[server.key];
        return next;
      });
      toast.error(e?.message || "Не удалось получить инструменты");
    }
  };

  const renderTools = (server: UnifiedServer) => {
    const tools = toolsByKey[server.key];
    if (!tools) return null;
    if (tools === "loading") {
      return (
        <div className="text-xs text-muted-foreground pl-1">Загрузка…</div>
      );
    }
    if (tools.length === 0) {
      return (
        <div className="text-xs text-muted-foreground pl-1">
          Нет инструментов
        </div>
      );
    }
    return (
      <div>
        <h4 className="font-medium text-sm mb-2">
          Доступные инструменты ({tools.length})
        </h4>
        <div className="border rounded p-2 bg-muted max-h-40 overflow-y-auto">
          <div className="flex flex-wrap gap-1">
            {tools.map((t) => (
              <Popover key={t.name}>
                <PopoverTrigger asChild>
                  <Badge variant="default" className="font-mono cursor-pointer">
                    {t.name}
                  </Badge>
                </PopoverTrigger>
                <PopoverContent align="start" className="z-1000">
                  <div className="space-y-2 min-w-0">
                    <div className="font-medium text-sm font-mono break-words [overflow-wrap:anywhere]">
                      {t.name}
                    </div>
                    {t.description ? (
                      <div className="text-xs text-muted-foreground break-words [overflow-wrap:anywhere]">
                        {t.description}
                      </div>
                    ) : (
                      <div className="text-xs text-muted-foreground">
                        Нет описания
                      </div>
                    )}
                  </div>
                </PopoverContent>
              </Popover>
            ))}
          </div>
        </div>
      </div>
    );
  };

  return (
    <>
      {RUNTIME_LOCAL && (
        <div className="flex items-center justify-end gap-2">
          <Button size="sm" variant="outline" onClick={openLocalConfig}>
            <FileCog size={14} className="mr-1" />
            mcp.json
          </Button>
        </div>
      )}

      <div className="overflow-y-auto flex-1 -mr-2 pr-2 space-y-3">
        {connectedModules.map((m) => {
          const hid = `module:${m.module_id}`;
          const needsAuth = m.status === "needs_reauth";
          return (
            <div key={hid} ref={cardRef(hid)} className={cardClass(hid)}>
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-start gap-2 min-w-0 flex-1">
                  <ConnectorIcon src={m.icon} className="h-6 w-6 mt-0.5" />
                  <div className="min-w-0 flex-1">
                    <div className="font-medium break-words">{m.name}</div>
                    {m.description && (
                      <div className="text-xs text-muted-foreground break-words [overflow-wrap:anywhere]">
                        {m.description}
                      </div>
                    )}
                  </div>
                </div>
                <Switch
                  checked={enabledModules[m.module_id] ?? m.enabled}
                  onCheckedChange={(checked) =>
                    toggleModule(m.module_id, Boolean(checked))
                  }
                />
              </div>
              <div className="flex items-center gap-1 flex-wrap">
                {needsAuth && NEEDS_AUTH_BADGE}
                {needsAuth && (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={moduleBusy === m.provider_key}
                    onClick={() => authorizeModule(m)}
                  >
                    <ShieldCheck size={14} className="mr-1" />
                    Авторизоваться
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="ghost"
                  className="text-destructive ml-auto"
                  disabled={moduleBusy === m.provider_key}
                  onClick={() => disconnectModule(m.provider_key)}
                >
                  <Trash2 size={14} />
                </Button>
              </div>
            </div>
          );
        })}
        {connectors.length === 0 &&
          connectedModules.length === 0 &&
          !loading && (
            <div className="text-sm text-muted-foreground py-6 text-center">
              Коннекторов пока нет. Нажмите «Добавить коннектор».
            </div>
          )}
        {connectors.map((server) => {
          const expanded = Boolean(toolsByKey[server.key]);
          const icon = iconForConnector(server, catalog);
          const isDb = server.source === "db";
          const hid = `${server.source}:${server.id}`;
          const needsAuth =
            isDb && server.auth_type === "oauth2" && !server.has_token;
          return (
            <div key={hid} ref={cardRef(hid)} className={cardClass(hid)}>
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-start gap-2 min-w-0 flex-1">
                  <ConnectorIcon src={icon} className="h-6 w-6 mt-0.5" />
                  <div className="min-w-0 flex-1">
                    <div className="font-medium break-words">{server.name}</div>
                    {server.command && (
                      <div className="text-xs text-muted-foreground break-all">
                        {server.command}
                      </div>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <Switch
                    checked={server.is_active}
                    disabled={busyId === server.id}
                    onCheckedChange={(checked) =>
                      toggleActive(server.id, Boolean(checked))
                    }
                  />
                </div>
              </div>

              <div className="flex items-center gap-1 flex-wrap">
                {server.transport && (
                  <Badge variant="outline">{server.transport}</Badge>
                )}
                {server.is_local && <Badge variant="outline">local</Badge>}
                {typeof server.tool_count === "number" && (
                  <Badge variant="secondary">{server.tool_count} tools</Badge>
                )}
                {needsAuth && NEEDS_AUTH_BADGE}
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => toggleTools(server)}
                >
                  {expanded ? (
                    <ChevronDown size={14} className="mr-1" />
                  ) : (
                    <ChevronRight size={14} className="mr-1" />
                  )}
                  <Wrench size={14} className="mr-1" />
                  Инструменты
                </Button>

                {isDb && (
                  <>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={busyId === server.id}
                      onClick={() => test(server.id)}
                    >
                      <Plug size={14} className="mr-1" />
                      Проверить
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={busyId === server.id}
                      onClick={() => refresh(server.id)}
                    >
                      <RefreshCw size={14} className="mr-1" />
                      Обновить
                    </Button>
                    {server.auth_type === "oauth2" && (
                      <Button
                        size="sm"
                        variant={needsAuth ? "default" : "outline"}
                        disabled={busyId === server.id}
                        onClick={() => authorize(server.id)}
                      >
                        <ShieldCheck size={14} className="mr-1" />
                        {server.has_token
                          ? "Переавторизоваться"
                          : "Авторизоваться"}
                      </Button>
                    )}
                    {server.can_edit && (
                      <Button
                        size="sm"
                        variant="ghost"
                        className="text-destructive ml-auto"
                        disabled={busyId === server.id}
                        onClick={() => remove(server.id)}
                      >
                        <Trash2 size={14} />
                      </Button>
                    )}
                  </>
                )}
              </div>

              {renderTools(server)}
            </div>
          );
        })}
      </div>
    </>
  );
};

export default ConnectorsConnectedTab;
