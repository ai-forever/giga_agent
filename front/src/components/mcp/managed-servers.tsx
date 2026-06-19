import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Plus,
  Trash2,
  RefreshCw,
  Plug,
  ShieldCheck,
  ChevronDown,
  ChevronRight,
  FileCog,
  Wrench,
} from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input, SecretInput } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { apiClient } from "@/lib/api-client";
import { API_AGENT_PREFIX, RUNTIME_LOCAL } from "@/config.ts";

type AuthType = "none" | "bearer" | "oauth2";

interface ToolInfo {
  name: string;
  description?: string;
}

interface UnifiedServer {
  key: string; // model-facing name, used for tools-by-name
  id: string; // uuid (db) or name (local)
  name: string;
  url?: string | null;
  command?: string | null;
  transport?: string;
  auth_type: AuthType | string;
  is_local: boolean;
  source: "db" | "file";
  has_token?: boolean;
  tool_count?: number | null;
  can_edit?: boolean;
}

interface DbServer {
  id: string;
  name?: string | null;
  url: string;
  auth_type: AuthType;
  is_local: boolean;
  has_token: boolean;
  tool_count?: number | null;
  can_edit: boolean;
}

interface LocalServer {
  id: string;
  name: string;
  transport: string;
  url?: string | null;
  command?: string | null;
  is_local: boolean;
  auth_type: string;
}

const MCP_SERVERS_URL = `${API_AGENT_PREFIX}/mcp/servers`;

const ManagedServers: React.FC = () => {
  const [servers, setServers] = useState<UnifiedServer[]>([]);
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [configPath, setConfigPath] = useState<string | null>(null);

  // Per-server expanded tools: key -> tools | "loading"
  const [toolsByKey, setToolsByKey] = useState<
    Record<string, ToolInfo[] | "loading">
  >({});

  // New server form
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [authType, setAuthType] = useState<AuthType>("none");
  const [token, setToken] = useState("");
  const [scope, setScope] = useState("");
  const [creating, setCreating] = useState(false);

  const oauthWindowRef = useRef<Window | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const db = await apiClient.get<DbServer[]>(MCP_SERVERS_URL);
      const merged: UnifiedServer[] = db.map((s) => ({
        key: s.name || s.id,
        id: s.id,
        name: s.name || s.url,
        url: s.url,
        auth_type: s.auth_type,
        is_local: s.is_local,
        source: "db",
        has_token: s.has_token,
        tool_count: s.tool_count,
        can_edit: s.can_edit,
      }));
      if (RUNTIME_LOCAL) {
        try {
          const local = await apiClient.get<LocalServer[]>(
            `${MCP_SERVERS_URL}/local`,
          );
          for (const s of local) {
            merged.push({
              key: s.name,
              id: s.id,
              name: s.name,
              url: s.url,
              command: s.command,
              transport: s.transport,
              auth_type: s.auth_type,
              is_local: s.is_local,
              source: "file",
            });
          }
        } catch {
          /* local config optional */
        }
      }
      setServers(merged);
    } catch (e: any) {
      toast.error(e?.message || "Не удалось загрузить серверы MCP");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    if (RUNTIME_LOCAL) {
      apiClient
        .get<{ path: string }>(`${MCP_SERVERS_URL}/local-config`)
        .then((r) => setConfigPath(r.path))
        .catch(() => {});
    }
  }, [load]);

  const toggleTools = async (server: UnifiedServer) => {
    const existing = toolsByKey[server.key];
    if (existing && existing !== "loading") {
      setToolsByKey((prev) => {
        const next = { ...prev };
        delete next[server.key];
        return next;
      });
      return;
    }
    setToolsByKey((prev) => ({ ...prev, [server.key]: "loading" }));
    try {
      const res = await apiClient.get<{ tools: ToolInfo[] }>(
        `${MCP_SERVERS_URL}/tools-by-name/${encodeURIComponent(server.key)}`,
      );
      setToolsByKey((prev) => ({ ...prev, [server.key]: res.tools }));
    } catch (e: any) {
      setToolsByKey((prev) => {
        const next = { ...prev };
        delete next[server.key];
        return next;
      });
      toast.error(e?.message || "Не удалось получить инструменты");
    }
  };

  const handleCreate = async () => {
    if (!url.trim()) {
      toast.error("Укажите URL сервера");
      return;
    }
    const settings: Record<string, unknown> = {};
    if (authType === "bearer") settings.token = token;
    if (authType === "oauth2") {
      if (scope.trim()) settings.scope = scope.trim();
      settings.use_dcr = true;
    }
    setCreating(true);
    try {
      await apiClient.post(MCP_SERVERS_URL, {
        name: name.trim() || undefined,
        url: url.trim(),
        auth_type: authType,
        settings,
        is_active: true,
        check_connection: authType !== "oauth2",
      });
      toast.success("Сервер добавлен");
      setName("");
      setUrl("");
      setToken("");
      setScope("");
      setAuthType("none");
      await load();
    } catch (e: any) {
      toast.error(e?.message || "Не удалось добавить сервер");
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (id: string) => {
    setBusyId(id);
    try {
      await apiClient.delete(`${MCP_SERVERS_URL}/${id}`);
      setServers((prev) => prev.filter((s) => s.id !== id));
    } catch (e: any) {
      toast.error(e?.message || "Не удалось удалить сервер");
    } finally {
      setBusyId(null);
    }
  };

  const handleTest = async (id: string) => {
    setBusyId(id);
    try {
      const res = await apiClient.post<{
        ok: boolean;
        tool_count: number | null;
        auth_required: boolean;
      }>(`${MCP_SERVERS_URL}/${id}/test-connection`);
      if (res.auth_required) {
        toast.info("Требуется авторизация — нажмите «Авторизоваться»");
      } else if (res.ok) {
        toast.success(
          `Подключение успешно: инструментов ${res.tool_count ?? 0}`,
        );
      } else {
        toast.error("Подключение не удалось");
      }
      await load();
    } catch (e: any) {
      toast.error(e?.message || "Проверка подключения не удалась");
    } finally {
      setBusyId(null);
    }
  };

  const handleRefresh = async (id: string) => {
    setBusyId(id);
    try {
      const res = await apiClient.post<{ tool_count: number }>(
        `${MCP_SERVERS_URL}/${id}/refresh-tools`,
      );
      toast.success(`Обновлено: инструментов ${res.tool_count}`);
      await load();
    } catch (e: any) {
      toast.error(e?.message || "Не удалось обновить инструменты");
    } finally {
      setBusyId(null);
    }
  };

  const handleAuthorize = async (id: string) => {
    setBusyId(id);
    try {
      const { authorization_url } = await apiClient.get<{
        authorization_url: string;
      }>(`${MCP_SERVERS_URL}/${id}/oauth/start`);
      oauthWindowRef.current = window.open(
        authorization_url,
        "mcp_oauth",
        "width=520,height=720",
      );
    } catch (e: any) {
      toast.error(e?.message || "Не удалось начать авторизацию");
    } finally {
      setBusyId(null);
    }
  };

  const handleOpenConfig = async () => {
    try {
      await apiClient.post(`${MCP_SERVERS_URL}/local-config/open`);
      toast.success("Файл mcp.json открыт в редакторе");
    } catch (e: any) {
      toast.error(e?.message || "Не удалось открыть файл");
    }
  };

  // Listen for the backend OAuth callback postMessage.
  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      const data = event.data;
      if (!data || data.type !== "mcp_auth_callback") return;
      if (data.success) {
        toast.success("Авторизация прошла успешно");
        load();
      } else {
        toast.error(`Авторизация не удалась: ${data.error || "ошибка"}`);
      }
      try {
        oauthWindowRef.current?.close();
      } catch {
        /* noop */
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [load]);

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
      <div className="mt-1 space-y-1 border-l pl-3">
        {tools.map((t) => (
          <div key={t.name} className="text-xs">
            <span className="font-mono">{t.name}</span>
            {t.description && (
              <span className="text-muted-foreground"> — {t.description}</span>
            )}
          </div>
        ))}
      </div>
    );
  };

  return (
    <div className="overflow-y-auto max-h-[60vh] space-y-4">
      <p className="text-sm text-muted-foreground">
        Серверы, выполняемые на бэкенде. Агент вызывает их инструменты через
        mcp_get_info / mcp_call_tool. Localhost-серверы работают только если
        бэкенд запущен локально.
      </p>

      {RUNTIME_LOCAL && (
        <div className="rounded-md border bg-muted/40 p-3 flex items-center justify-between gap-2">
          <div className="min-w-0">
            <div className="font-medium text-sm">
              Локальные серверы (mcp.json)
            </div>
            {configPath && (
              <div className="text-xs text-muted-foreground break-all">
                {configPath}
              </div>
            )}
          </div>
          <Button size="sm" variant="outline" onClick={handleOpenConfig}>
            <FileCog size={14} className="mr-1" />
            Открыть mcp.json
          </Button>
        </div>
      )}

      {/* Server list */}
      <div className="space-y-3">
        {servers.length === 0 && !loading && (
          <div className="text-sm text-muted-foreground">
            Серверов пока нет.
          </div>
        )}
        {servers.map((server) => {
          const expanded =
            toolsByKey[server.key] && toolsByKey[server.key] !== undefined;
          return (
            <div
              key={`${server.source}:${server.id}`}
              className="rounded-md border bg-card p-3 flex flex-col gap-2"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 flex-1">
                  <div className="font-medium break-words">{server.name}</div>
                  <div className="text-xs text-muted-foreground break-all">
                    {server.url || server.command}
                  </div>
                </div>
                <div className="flex items-center gap-1 shrink-0 flex-wrap justify-end">
                  <Badge variant="outline">{server.auth_type}</Badge>
                  {server.transport && (
                    <Badge variant="outline">{server.transport}</Badge>
                  )}
                  <Badge variant="outline">
                    {server.source === "file" ? "file" : "db"}
                  </Badge>
                  {server.is_local && <Badge variant="outline">local</Badge>}
                  {typeof server.tool_count === "number" && (
                    <Badge variant="secondary">{server.tool_count} tools</Badge>
                  )}
                </div>
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

                {server.source === "db" && (
                  <>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={busyId === server.id}
                      onClick={() => handleTest(server.id)}
                    >
                      <Plug size={14} className="mr-1" />
                      Проверить
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={busyId === server.id}
                      onClick={() => handleRefresh(server.id)}
                    >
                      <RefreshCw size={14} className="mr-1" />
                      Обновить
                    </Button>
                    {server.auth_type === "oauth2" && (
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={busyId === server.id}
                        onClick={() => handleAuthorize(server.id)}
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
                        onClick={() => handleDelete(server.id)}
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

      {/* Add new server */}
      <div className="rounded-md border bg-muted/40 p-3 space-y-3">
        <div className="font-medium text-sm">Добавить сервер</div>
        <Input
          placeholder="Название (необязательно)"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <Input
          placeholder="https://mcp.example.com/mcp"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
        />
        <div className="flex items-center gap-2">
          {(["none", "bearer", "oauth2"] as AuthType[]).map((t) => (
            <Badge
              key={t}
              variant={authType === t ? "default" : "outline"}
              className="cursor-pointer"
              onClick={() => setAuthType(t)}
            >
              {t}
            </Badge>
          ))}
        </div>
        {authType === "bearer" && (
          <SecretInput
            placeholder="Bearer-токен"
            value={token}
            onChange={(e) => setToken(e.target.value)}
          />
        )}
        {authType === "oauth2" && (
          <Input
            placeholder="OAuth scope (необязательно)"
            value={scope}
            onChange={(e) => setScope(e.target.value)}
          />
        )}
        <Button size="sm" onClick={handleCreate} disabled={creating}>
          <Plus size={14} className="mr-1" />
          Добавить
        </Button>
      </div>
    </div>
  );
};

export default ManagedServers;
