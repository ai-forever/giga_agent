import React, { useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  FileCog,
  Plug,
  Plus,
  RefreshCw,
  ShieldCheck,
  Trash2,
  Wrench,
} from "lucide-react";
import { toast } from "sonner";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { API_AGENT_PREFIX, RUNTIME_LOCAL } from "@/config.ts";
import { apiClient } from "@/lib/api-client";
import { useUserInfo } from "@/components/providers/user-info";
import { iconForConnector } from "./types";
import type { ToolInfo, UnifiedServer } from "./types";
import type { UseConnectorsResult } from "./use-connectors";

const INTEGRATIONS_URL = `${API_AGENT_PREFIX}/integrations`;

interface ManageModalProps {
  isOpen: boolean;
  onClose: () => void;
  api: UseConnectorsResult;
  onAdd: () => void;
}

const ConnectorsManageModal: React.FC<ManageModalProps> = ({
  isOpen,
  onClose,
  api,
  onAdd,
}) => {
  const {
    connectors,
    catalog,
    moduleCatalog,
    reloadCatalog,
    loading,
    busyId,
    configPath,
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
  const connectedModules = moduleCatalog.filter((m) => m.status === "connected");

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
      return <div className="text-xs text-muted-foreground pl-1">Загрузка…</div>;
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
    <Dialog open={isOpen} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-2xl max-h-[85vh] flex flex-col gap-4">
        <DialogHeader>
          <DialogTitle>Управление коннекторами</DialogTitle>
          <DialogDescription>
            Подключённые серверы выполняются на бэкенде. Агент использует
            инструменты только активных коннекторов.
          </DialogDescription>
        </DialogHeader>

        <div className="flex items-center justify-between gap-2">
          <Button variant="default" size="sm" onClick={onAdd}>
            <Plus className="size-4 mr-1" />
            Добавить коннектор
          </Button>
          {RUNTIME_LOCAL && (
            <Button size="sm" variant="outline" onClick={openLocalConfig}>
              <FileCog size={14} className="mr-1" />
              mcp.json
            </Button>
          )}
        </div>

        {RUNTIME_LOCAL && configPath && (
          <div className="text-xs text-muted-foreground break-all">
            {configPath}
          </div>
        )}

        <div className="overflow-y-auto flex-1 -mr-2 pr-2 space-y-3">
          {connectedModules.map((m) => (
            <div
              key={`module:${m.module_id}`}
              className="rounded-md border bg-card p-3 flex flex-col gap-2"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-start gap-2 min-w-0 flex-1">
                  {m.icon && (
                    <img
                      src={m.icon}
                      alt=""
                      className="h-6 w-6 rounded shrink-0 mt-0.5"
                      onError={(e) => {
                        e.currentTarget.style.display = "none";
                      }}
                    />
                  )}
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
                <Badge variant="outline">модуль</Badge>
                <Badge variant="secondary">
                  {m.auth_kind === "oauth2" ? "oauth2" : "token"}
                </Badge>
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
          ))}
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
            return (
              <div
                key={`${server.source}:${server.id}`}
                className="rounded-md border bg-card p-3 flex flex-col gap-2"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-start gap-2 min-w-0 flex-1">
                    {icon && (
                      <img
                        src={icon}
                        alt=""
                        className="h-6 w-6 rounded shrink-0 mt-0.5"
                        onError={(e) => {
                          e.currentTarget.style.display = "none";
                        }}
                      />
                    )}
                    <div className="min-w-0 flex-1">
                      <div className="font-medium break-words">
                        {server.name}
                      </div>
                      <div className="text-xs text-muted-foreground break-all">
                        {server.url || server.command}
                      </div>
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
                  <Badge variant="outline">{server.auth_type}</Badge>
                  {server.transport && (
                    <Badge variant="outline">{server.transport}</Badge>
                  )}
                  {server.is_local && <Badge variant="outline">local</Badge>}
                  {typeof server.tool_count === "number" && (
                    <Badge variant="secondary">{server.tool_count} tools</Badge>
                  )}
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
                          variant="outline"
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
      </DialogContent>
    </Dialog>
  );
};

export default ConnectorsManageModal;
