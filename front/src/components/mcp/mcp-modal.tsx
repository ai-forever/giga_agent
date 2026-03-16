import React, { useState, useEffect, useRef, useMemo } from "react";
import { Info, Plus, Trash2, Power, PowerOff, X } from "lucide-react";
import { toast } from "sonner";
import { type Tool } from "@modelcontextprotocol/sdk/types.js";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input, SecretInput } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Switch } from "@/components/ui/switch";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { detectGigaChatWrongSchema } from "@/components/mcp/utils/detectGigaChatWrongSchema";
import { MCP_PROXY_URL } from "@/config.ts";
import { useMcp } from "@/components/mcp/hooks/useMcp.ts";

interface McpServer {
  id: string;
  url: string;
  enabled: boolean;
  name?: string;
  transportType: "auto" | "http" | "sse";
  authToken?: string;
}

const resolveUrlForTransport = (rawUrl: string): string => {
  try {
    const target = new URL(rawUrl);
    const host = target.hostname.toLowerCase();

    const isIPv4 = /^\d{1,3}(\.\d{1,3}){3}$/.test(host);
    const isIPv6 = host.includes(":");

    const isLocalHostname =
      host === "localhost" ||
      host === "0.0.0.0" ||
      host === "::1" ||
      host.endsWith(".local");

    let isPrivateLan = false;
    if (isIPv4) {
      const [a, b] = host.split(".").map((n) => parseInt(n, 10));
      if (a === 10) isPrivateLan = true; // 10.0.0.0/8
      if (a === 127) isPrivateLan = true; // 127.0.0.0/8 loopback
      if (a === 192 && b === 168) isPrivateLan = true; // 192.168.0.0/16
      if (a === 172 && b >= 16 && b <= 31) isPrivateLan = true; // 172.16.0.0/12
      if (a === 169 && b === 254) isPrivateLan = true; // 169.254.0.0/16 link-local
      if (a === 100 && b >= 64 && b <= 127) isPrivateLan = true; // 100.64.0.0/10 CGNAT
    }
    if (isIPv6) {
      const h = host;
      if (h === "::1") isPrivateLan = true; // loopback
      if (h.startsWith("fe80:")) isPrivateLan = true; // link-local
      if (h.startsWith("fc") || h.startsWith("fd")) isPrivateLan = true; // unique local
    }

    const isLocal = isLocalHostname || isPrivateLan;
    if (isLocal) return rawUrl;
    // Remote host → используем локальный прокси
    const proxyUrl = MCP_PROXY_URL
      ? MCP_PROXY_URL
      : `${window.location.protocol}//${window.location.host}/proxy/`;
    return `${rawUrl}`;
  } catch {
    // Если URL некорректный — возвращаем как есть
    return rawUrl;
  }
};

// MCP Connection wrapper for a single server
function McpConnection({
  server,
  onConnectionUpdate,
}: {
  server: McpServer;
  onConnectionUpdate: (serverId: string, data: any) => void;
}) {
  // Use the MCP hook with the server URL
  const effectiveUrl = useMemo(
    () => resolveUrlForTransport(server.url),
    [server.url],
  );

  const connection = useMcp({
    enabled: server.enabled,
    url: effectiveUrl,
    debug: true,
    autoRetry: false,
    popupFeatures: "width=500,height=600,resizable=yes,scrollbars=yes",
    transportType: server.transportType,
    callbackUrl: window.location.origin + "/oauth/callback",
    clientName: "GigaAgent",
    autoReconnect: 3000,
    timeout: 15000,
    customHeaders: server.authToken
      ? { Authorization: `Bearer ${server.authToken}` }
      : undefined,
    preventAutoAuth: false, // Prevent automatic popups on page load
  });

  // Update parent component with connection data
  useEffect(() => {
    onConnectionUpdate(server.id, connection);
  }, [
    server.id,
    connection.state,
    connection.tools,
    connection.error,
    connection.log.length,
    connection.authUrl,
  ]);

  // Return null as this is just a hook wrapper
  return null;
}

const MCPConnectionMemo = React.memo(
  McpConnection,
  (prev, next) => prev.server.url === next.server.url,
);

type ToolWithEnabled = Tool & { enabled: boolean; disabled?: boolean };

export type MCPTool = Tool & {
  callTool: (args: Record<string, unknown>) => Promise<any>;
};

interface McpServerModalProps {
  isOpen: boolean;
  onClose: () => void;
  onToolsUpdate?: (tools: MCPTool[]) => void;
}

const McpServerModal: React.FC<McpServerModalProps> = ({
  isOpen,
  onClose,
  onToolsUpdate,
}) => {
  // Локальное состояние тулов по серверу с флагом enabled
  const [serverTools, setServerTools] = useState<
    Record<string, ToolWithEnabled[]>
  >({});
  const TOOLS_STORAGE_KEY = "mcpServerTools";

  // Хелпер: персистентное обновление serverTools (включая запись в localStorage)
  const updateServerTools = (
    updater: (
      prev: Record<string, ToolWithEnabled[]>,
    ) => Record<string, ToolWithEnabled[]>,
  ) => {
    setServerTools((prev) => {
      const next = updater(prev);
      try {
        localStorage.setItem(TOOLS_STORAGE_KEY, JSON.stringify(next));
      } catch {
        // ignore
      }
      return next;
    });
  };

  // Инициализация serverTools из localStorage (персистентность)
  useEffect(() => {
    try {
      const stored = localStorage.getItem(TOOLS_STORAGE_KEY);
      if (stored) {
        const parsed = JSON.parse(stored);
        if (parsed && typeof parsed === "object") {
          setServerTools(parsed);
        }
      }
    } catch {
      // ignore
    }
  }, []);

  const [servers, setServers] = useState<McpServer[]>(() => {
    const stored = localStorage.getItem("mcpServers");
    return stored ? JSON.parse(stored) : [];
  });
  const [newServerUrl, setNewServerUrl] = useState("");
  const [showAuthTokenInput, setShowAuthTokenInput] = useState(false);
  const [newServerAuthToken, setNewServerAuthToken] = useState("");
  const [connectionData, setConnectionData] = useState<Record<string, any>>({});
  const [transportType, _setTransportType] = useState<"auto" | "http" | "sse">(
    () => {
      const stored = localStorage.getItem("mcpTransportType");
      return (stored as "auto" | "http" | "sse") || "auto";
    },
  );
  const [newServerTransportType, setNewServerTransportType] = useState<
    "auto" | "http" | "sse"
  >("auto");

  const connectionToastsRef = useRef<
    Record<string, string | number | undefined>
  >({});
  const successfulConnectionsRef = useRef<Set<string>>(new Set());

  const dismissConnectionToast = (serverId: string) => {
    const prevToastId = connectionToastsRef.current[serverId];
    if (prevToastId !== undefined) {
      toast.dismiss(prevToastId);
      delete connectionToastsRef.current[serverId];
    }
  };

  const showConnectionToast = (
    serverId: string,
    variant: "loading" | "success" | "error" | "warning",
    message: string,
  ) => {
    dismissConnectionToast(serverId);

    switch (variant) {
      case "loading": {
        if (!(serverId in connectionToastsRef.current)) {
          connectionToastsRef.current[serverId] = toast.loading(message);
        }
        break;
      }
      case "success":
        toast.success(message);
        break;
      case "error":
        toast.error(message);
        break;
      case "warning":
        toast.warning(message);
        break;
    }
  };

  const getToastConfigForState = (
    state: string | undefined,
    url: string | undefined,
  ):
    | {
        variant: "loading" | "success" | "error" | "warning";
        message: string;
      }
    | undefined => {
    let baseDomain: string | undefined = url;
    if (url) {
      try {
        baseDomain = new URL(url).hostname;
      } catch {
        baseDomain = url;
      }
    }
    if (!state || !baseDomain) return undefined;

    switch (state) {
      case "discovering":
        return {
          variant: "loading",
          message: `Подключение к MCP ${baseDomain}`,
        };
      case "connecting":
        return {
          variant: "loading",
          message: `Подключение к MCP ${baseDomain}`,
        };
      case "authenticating":
        return {
          variant: "loading",
          message: `Аутентификация на MCP ${baseDomain}`,
        };
      case "pending_auth":
        return {
          variant: "warning",
          message: `Для MCP ${baseDomain} требуется аутентификация`,
        };
      case "loading":
        return {
          variant: "loading",
          message: `Загрузка инструментов MCP ${baseDomain}`,
        };
      case "ready":
        return {
          variant: "success",
          message: `MCP ${baseDomain} успешно подключён`,
        };
      case "failed":
        return {
          variant: "error",
          message: `Ошибка подключения к MCP ${baseDomain}`,
        };
      default:
        return undefined;
    }
  };

  // Helper to cycle through new server transport types
  const cycleNewServerTransportType = () => {
    setNewServerTransportType((current) => {
      switch (current) {
        case "auto":
          return "http";
        case "http":
          return "sse";
        case "sse":
          return "auto";
        default:
          return "http";
      }
    });
  };
  // const logRef = useRef<HTMLDivElement>(null) // Removed for now as debug logs not implemented in multi-server version

  // Save servers to localStorage whenever they change
  useEffect(() => {
    localStorage.setItem("mcpServers", JSON.stringify(servers));
  }, [servers]);

  // Save transport type to localStorage whenever it changes
  useEffect(() => {
    localStorage.setItem("mcpTransportType", transportType);
  }, [transportType]);

  // Dialog сам управляет оверлеем/скроллом

  // Aggregate all tools from enabled servers and notify parent
  useEffect(() => {
    const allTools: MCPTool[] = [];

    servers.forEach((server) => {
      if (!server.enabled || connectionData[server.id]?.state !== "ready")
        return;
      const list = serverTools[server.id];
      if (!list || list.length === 0) return;
      const activeTools = list.filter((t) => t.enabled);
      if (activeTools.length === 0) return;
      const withCallTool = activeTools.map((t) => ({
        ...t,
        callTool: (args: Record<string, unknown>) =>
          connectionData[server.id].callTool(t.name, args),
      }));
      allTools.push(...withCallTool);
    });

    if (onToolsUpdate) {
      onToolsUpdate(allTools);
    }
  }, [servers, connectionData, serverTools, onToolsUpdate]);

  // Handle adding a new server
  const handleAddServer = () => {
    if (!newServerUrl.trim()) return;

    const newServer: McpServer = {
      id: Date.now().toString(),
      url: newServerUrl.trim(),
      enabled: true,
      name: new URL(newServerUrl.trim()).hostname,
      transportType: newServerTransportType,
      authToken: newServerAuthToken.trim()
        ? newServerAuthToken.trim()
        : undefined,
    };

    setServers((prev) => [...prev, newServer]);
    setNewServerUrl("");
    setNewServerAuthToken("");
    setShowAuthTokenInput(false);
  };

  // Handle removing a server
  const handleRemoveServer = (serverId: string) => {
    // Disconnect if connected
    const connection = connectionData[serverId];
    if (connection?.disconnect) {
      connection.disconnect();
    }
    connection.clearStorage();

    dismissConnectionToast(serverId);
    successfulConnectionsRef.current.delete(serverId);
    setServers((prev) => prev.filter((s) => s.id !== serverId));
    setConnectionData((prev) => {
      const newData = { ...prev };
      delete newData[serverId];
      return newData;
    });
    // Удаляем информацию о тулах для этого сервера
    updateServerTools((prev) => {
      const next = { ...prev };
      delete next[serverId];
      return next;
    });
  };

  // Handle toggling server enabled state
  const handleToggleServer = (serverId: string) => {
    dismissConnectionToast(serverId);
    setServers((prev) =>
      prev.map((server) =>
        server.id === serverId
          ? { ...server, enabled: !server.enabled }
          : server,
      ),
    );

    // If disabling, disconnect
    const server = servers.find((s) => s.id === serverId);
    if (server?.enabled && connectionData[serverId]?.disconnect) {
      connectionData[serverId].disconnect();
    }
    if (server?.enabled) {
      successfulConnectionsRef.current.delete(serverId);
    }
  };

  // Handle connection update for a specific server
  const handleConnectionUpdate = (serverId: string, data: any) => {
    setConnectionData((prev) => ({
      ...prev,
      [serverId]: data,
    }));

    const state: string | undefined = data?.state;
    const server = servers.find((s) => s.id === serverId);
    const url = server?.url;

    const toastConfig = getToastConfigForState(state, url);
    if (toastConfig) {
      const { variant, message } = toastConfig;

      if (variant === "success") {
        if (successfulConnectionsRef.current.has(serverId)) {
          dismissConnectionToast(serverId);
          return;
        }
        successfulConnectionsRef.current.add(serverId);
      } else {
        successfulConnectionsRef.current.delete(serverId);
      }

      showConnectionToast(serverId, variant, message);
    }

    // Обновляем "список доступных тулов" только при готовом соединении:
    // - если записи по серверу нет → инициализируем из incoming (enabled=true)
    // - если запись есть → выполняем синхронизацию:
    //     сохраняем существующие (ничего не меняем),
    //     удаляем отсутствующие во входящих,
    //     добавляем новые входящие с enabled=true.
    // При пустом incoming или неготовом состоянии — не трогаем запись.
    try {
      const incoming: Tool[] = Array.isArray(data?.tools) ? data.tools : [];
      const isReady = data?.state === "ready";
      if (!isReady || incoming.length === 0) return;
      updateServerTools((prev) => {
        const prevList = prev[serverId];
        if (!prevList || prevList.length === 0) {
          const nextList: ToolWithEnabled[] = incoming.map((t) => {
            const isWrong =
              t && "inputSchema" in t
                ? detectGigaChatWrongSchema((t as any).inputSchema)
                : false;
            return {
              ...t,
              enabled: isWrong ? false : true,
              disabled: isWrong,
            };
          });
          return { ...prev, [serverId]: nextList };
        }
        const incomingNames = new Set(incoming.map((t) => t.name));
        // Оставляем только те, что есть во входящих
        const kept = prevList
          .filter((t) => incomingNames.has(t.name))
          .map((existing) => {
            const inc = incoming.find((it) => it.name === existing.name);
            const isWrong =
              inc && "inputSchema" in inc
                ? detectGigaChatWrongSchema((inc as any).inputSchema)
                : false;
            if (isWrong) {
              return {
                ...existing,
                disabled: true,
                enabled: false,
              };
            }
            return {
              ...existing,
              disabled: false,
            };
          });
        const keptNames = new Set(kept.map((t) => t.name));
        // Добавляем новые из входящих
        const added: ToolWithEnabled[] = incoming
          .filter((t) => !keptNames.has(t.name))
          .map((t) => {
            const isWrong =
              t && "inputSchema" in t
                ? detectGigaChatWrongSchema((t as any).inputSchema)
                : false;
            return {
              ...t,
              enabled: !isWrong,
              disabled: isWrong,
            };
          });
        // Существующие не изменяем (имя/описание/enabled остаются как были)
        const nextList: ToolWithEnabled[] = [...kept, ...added];
        return { ...prev, [serverId]: nextList };
      });
    } catch {
      // ignore
    }
  };

  // Handle authentication for a specific server
  const handleManualAuth = (serverId: string) => {
    try {
      const connection = connectionData[serverId];
      connection.authenticate();
    } catch (err) {
      console.error("Authentication error:", err);
    }
  };

  // Generate status badge based on connection state
  const getStatusBadge = (state: string) => {
    switch (state) {
      case "discovering":
        return <Badge variant="secondary">Подключение</Badge>;
      case "pending_auth":
        return <Badge variant="outline">Требуется аутентификация</Badge>;
      case "authenticating":
        return <Badge variant="secondary">Аутентификация</Badge>;
      case "connecting":
        return <Badge variant="secondary">Подключение</Badge>;
      case "loading":
        return <Badge variant="secondary">Загрузка</Badge>;
      case "ready":
        return <Badge>Подключено</Badge>;
      case "failed":
        return <Badge variant="destructive">Ошибка</Badge>;
      case "not-connected":
      default:
        return <Badge variant="outline">Не подключено</Badge>;
    }
  };

  return (
    <>
      <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
        <DialogContent className="w-full max-w-3xl">
          <DialogHeader>
            <div className="flex items-center justify-between">
              <DialogTitle>Серверы MCP</DialogTitle>
            </div>
            <DialogDescription>
              <span className="inline-flex items-center gap-2">
                <Info size={16} />
                Подключитесь к серверам Model Context Protocol (MCP), чтобы
                расширить возможности агента.
              </span>
            </DialogDescription>
          </DialogHeader>

          <div className="overflow-y-auto max-h-[60vh]">
            {/* Server List */}
            <div className="space-y-4 mb-6">
              {servers.map((server) => {
                const connection = connectionData[server.id] || {
                  state: "not-connected",
                  tools: [],
                  error: undefined,
                  authUrl: undefined,
                };
                const { state, tools, error, authUrl } = connection;

                return (
                  <div
                    key={server.id}
                    className={`bg-card border shadow-none dark:border-t-1 dark:border-l-0 dark:border-r-0 dark:border-b-0 dark:shadow-md border-highlight rounded-lg p-4 ${server.enabled ? "" : ""}`}
                  >
                    <div className="flex items-center justify-between mb-3">
                      <div className="flex items-center gap-3">
                        <div>
                          <div className="font-medium text-foreground">
                            {server.name || "MCP Server"}
                          </div>
                          <div className="text-sm text-muted-foreground break-all">
                            {server.url}
                          </div>
                        </div>
                      </div>

                      <div className="flex items-center gap-2">
                        {getStatusBadge(server.enabled ? state : "disabled")}
                        {server.enabled && state === "ready" && (
                          <Badge variant="outline" className="font-mono">
                            {server.transportType.toUpperCase()}
                          </Badge>
                        )}
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => handleToggleServer(server.id)}
                          title={
                            server.enabled
                              ? "Отключить сервер"
                              : "Включить сервер"
                          }
                          aria-label={
                            server.enabled
                              ? "Отключить сервер"
                              : "Включить сервер"
                          }
                        >
                          {server.enabled ? (
                            <Power size={16} />
                          ) : (
                            <PowerOff size={16} />
                          )}
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => handleRemoveServer(server.id)}
                          title="Удалить сервер"
                          aria-label="Удалить сервер"
                        >
                          <Trash2 size={16} />
                        </Button>
                      </div>
                    </div>

                    {server.enabled && (
                      <>
                        {error && state === "failed" && (
                          <Alert variant="destructive" className="mb-3">
                            <AlertDescription>{error}</AlertDescription>
                          </Alert>
                        )}

                        {(state === "pending_auth" || authUrl) && (
                          <div className="border rounded p-3 mb-3">
                            <p className="text-sm mb-2">
                              {state === "pending_auth"
                                ? "Для подключения к этому серверу требуется аутентификация."
                                : "Всплывающее окно аутентификации было заблокировано. Вы можете открыть страницу аутентификации вручную:"}
                            </p>
                            <div className="space-y-2">
                              <Button
                                className="w-full"
                                onClick={() => handleManualAuth(server.id)}
                              >
                                Открыть окно аутентификации
                              </Button>
                              {authUrl && (
                                <a
                                  href={authUrl}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="block text-center text-sm text-primary underline"
                                >
                                  Или открыть в новой вкладке
                                </a>
                              )}
                            </div>
                          </div>
                        )}

                        {state === "ready" && tools.length > 0 && (
                          <div>
                            <h4 className="font-medium text-sm mb-2">
                              Доступные инструменты ({tools.length})
                            </h4>
                            <div className="border rounded p-2 bg-muted max-h-24 overflow-y-auto">
                              <div className="flex flex-wrap gap-1">
                                {(serverTools[server.id] || []).map(
                                  (tool: ToolWithEnabled, index: number) => (
                                    <Popover key={`${tool.name}-${index}`}>
                                      <PopoverTrigger asChild>
                                        <Badge
                                          variant={
                                            tool.disabled
                                              ? "destructive"
                                              : tool.enabled
                                                ? "default"
                                                : "outline"
                                          }
                                          className={`${
                                            tool.disabled
                                              ? "cursor-not-allowed"
                                              : "cursor-pointer"
                                          } ${tool.enabled ? "" : "opacity-70"}`}
                                        >
                                          {tool.name}
                                        </Badge>
                                      </PopoverTrigger>
                                      <PopoverContent
                                        align="start"
                                        className="z-1000"
                                      >
                                        <div className="space-y-2">
                                          <div className="font-medium text-sm">
                                            {tool.name}
                                          </div>
                                          {tool.disabled && (
                                            <Badge
                                              variant="destructive"
                                              className="cursor-not-allowed"
                                              title="Этот инструмент отключён в GigaChat из‑за anyOf"
                                            >
                                              Инструмент отключён в GigaChat
                                              из‑за anyOf
                                            </Badge>
                                          )}
                                          {tool.description && (
                                            <div className="text-xs text-muted-foreground">
                                              {tool.description}
                                            </div>
                                          )}
                                          <div className="flex items-center justify-between pt-1">
                                            <span className="text-xs">
                                              Включён
                                            </span>
                                            <Switch
                                              disabled={Boolean(tool.disabled)}
                                              checked={tool.enabled}
                                              onCheckedChange={(checked) => {
                                                if (tool.disabled) return;
                                                updateServerTools((prev) => {
                                                  const list =
                                                    prev[server.id] || [];
                                                  const nextList = list.map(
                                                    (t, i) =>
                                                      i === index
                                                        ? {
                                                            ...t,
                                                            enabled:
                                                              Boolean(checked),
                                                          }
                                                        : t,
                                                  );
                                                  return {
                                                    ...prev,
                                                    [server.id]: nextList,
                                                  };
                                                });
                                              }}
                                            />
                                          </div>
                                        </div>
                                      </PopoverContent>
                                    </Popover>
                                  ),
                                )}
                              </div>
                            </div>
                          </div>
                        )}
                      </>
                    )}
                  </div>
                );
              })}

              {servers.length === 0 && (
                <div className="text-center py-8 text-muted-foreground">
                  <Info size={24} className="mx-auto mb-2" />
                  <p>Пока не настроено ни одного сервера MCP.</p>
                  <p className="text-sm">Добавьте первый сервер ниже.</p>
                </div>
              )}
            </div>

            {/* Add New Server */}
            <div className="border-t pt-4">
              <div className="flex items-center gap-3 mb-3">
                <h3 className="font-medium text-sm">Добавить новый сервер</h3>
                <Badge
                  variant="outline"
                  className="cursor-pointer font-mono"
                  onClick={cycleNewServerTransportType}
                  title="Нажмите, чтобы переключить тип подключения"
                >
                  {newServerTransportType.toUpperCase()}
                </Badge>
              </div>
              <div className="flex gap-2">
                <Input
                  type="text"
                  placeholder="Введите URL сервера MCP"
                  value={newServerUrl}
                  onChange={(e) => setNewServerUrl(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      handleAddServer();
                    }
                  }}
                />
                <Button
                  type="button"
                  variant={"default2"}
                  onClick={handleAddServer}
                  disabled={!newServerUrl.trim()}
                >
                  <Plus size={16} />
                </Button>
              </div>
              {!showAuthTokenInput && (
                <div className="mt-2">
                  <button
                    type="button"
                    className="text-xs text-primary underline cursor-pointer"
                    onClick={() => setShowAuthTokenInput(true)}
                  >
                    Добавить токен аутентификации
                  </button>
                </div>
              )}
              {showAuthTokenInput && (
                <div className="mt-2 relative">
                  <SecretInput
                    name="auth_token"
                    placeholder="Введите токен аутентификации"
                    value={newServerAuthToken}
                    onChange={(e) => setNewServerAuthToken(e.target.value)}
                  />
                  <div className="absolute right-1 top-1 z-1000">
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-6 w-6 rounded-full border bg-card hover:bg-muted"
                          aria-label="Удалить токен аутентификации"
                          onClick={() => {
                            setNewServerAuthToken("");
                            setShowAuthTokenInput(false);
                          }}
                        >
                          <X size={12} />
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent className="z-1000" sideOffset={4}>
                        Удалить токен аутентификации
                      </TooltipContent>
                    </Tooltip>
                  </div>
                </div>
              )}
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* Render MCP connections for all enabled servers */}
      {servers
        .filter((s) => s.enabled)
        .map((server) => (
          <MCPConnectionMemo
            key={server.id}
            server={server}
            onConnectionUpdate={handleConnectionUpdate}
          />
        ))}
    </>
  );
};

export default McpServerModal;
