import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { apiClient } from "@/lib/api-client";
import { useAuth } from "@/components/providers/auth.tsx";
import { API_AGENT_PREFIX, RUNTIME_LOCAL } from "@/config.ts";
import type {
  CatalogEntry,
  ConnectorsCatalog,
  CreateConnectorInput,
  DbServer,
  LocalServer,
  ModuleCatalogEntry,
  ToolInfo,
  UnifiedServer,
} from "./types";

const MCP_SERVERS_URL = `${API_AGENT_PREFIX}/mcp/servers`;
const CONNECTORS_CATALOG_URL = `${API_AGENT_PREFIX}/agent/connectors/catalog`;
const USER_ME_URL = `${API_AGENT_PREFIX}/auth/users/me`;

// Ключ в user.settings, где храним выключенные локальные серверы (по имени
// local_<ns>). Мирроринг бэкенд-константы LOCAL_DISABLED_SETTINGS_KEY.
const DISABLED_LOCAL_KEY = "disabledLocalServers";

function readDisabledLocal(
  settings: Record<string, unknown> | null | undefined,
): string[] {
  const raw = settings?.[DISABLED_LOCAL_KEY];
  if (!Array.isArray(raw)) return [];
  return raw.filter((x): x is string => typeof x === "string");
}

export interface TestResult {
  ok: boolean;
  tool_count: number | null;
  auth_required: boolean;
}

export interface UseConnectorsResult {
  connectors: UnifiedServer[];
  catalog: CatalogEntry[];
  loading: boolean;
  busyId: string | null;
  configPath: string | null;
  activeCount: number;
  moduleCatalog: ModuleCatalogEntry[];
  reloadCatalog: () => Promise<void>;
  reload: () => Promise<void>;
  toggleActive: (id: string, isActive: boolean) => Promise<void>;
  connect: (
    entryId: string,
    inputs: Record<string, string>,
  ) => Promise<DbServer>;
  createCustom: (input: CreateConnectorInput) => Promise<DbServer>;
  remove: (id: string) => Promise<void>;
  test: (id: string) => Promise<void>;
  refresh: (id: string) => Promise<void>;
  authorize: (id: string) => Promise<void>;
  fetchTools: (key: string) => Promise<ToolInfo[]>;
  openLocalConfig: () => Promise<void>;
}

function mergeDbServer(s: DbServer): UnifiedServer {
  return {
    key: s.name || s.id,
    id: s.id,
    name: s.name || s.url,
    url: s.url,
    auth_type: s.auth_type,
    is_active: s.is_active,
    is_local: s.is_local,
    source: "db",
    has_token: s.has_token,
    tool_count: s.tool_count,
    can_edit: s.can_edit,
  };
}

function mergeLocalServer(s: LocalServer): UnifiedServer {
  return {
    key: s.name,
    id: s.id,
    name: s.name,
    url: s.url,
    command: s.command,
    transport: s.transport,
    auth_type: s.auth_type,
    is_active: s.is_active ?? true,
    is_local: s.is_local,
    source: "file",
  };
}

export function useConnectors(): UseConnectorsResult {
  const { user, refreshUser } = useAuth();
  const [connectors, setConnectors] = useState<UnifiedServer[]>([]);
  const [catalog, setCatalog] = useState<CatalogEntry[]>([]);
  const [moduleCatalog, setModuleCatalog] = useState<ModuleCatalogEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [configPath, setConfigPath] = useState<string | null>(null);
  const oauthWindowRef = useRef<Window | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const db = await apiClient.get<DbServer[]>(MCP_SERVERS_URL);
      const merged: UnifiedServer[] = db.map(mergeDbServer);
      if (RUNTIME_LOCAL) {
        try {
          const local = await apiClient.get<LocalServer[]>(
            `${MCP_SERVERS_URL}/local`,
          );
          merged.push(...local.map(mergeLocalServer));
        } catch {
          /* local config optional */
        }
      }
      setConnectors(merged);
    } catch (e: any) {
      toast.error(e?.message || "Не удалось загрузить коннекторы");
    } finally {
      setLoading(false);
    }
  }, []);

  // Единый каталог (MCP-шаблоны + подключаемые модули) — собирается на бэке.
  const reloadCatalog = useCallback(async () => {
    try {
      const data = await apiClient.get<ConnectorsCatalog>(
        CONNECTORS_CATALOG_URL,
      );
      setCatalog(data.mcp ?? []);
      setModuleCatalog(data.modules ?? []);
    } catch {
      /* каталог опционален */
    }
  }, []);

  useEffect(() => {
    void reloadCatalog();
  }, [reloadCatalog]);

  useEffect(() => {
    void reload();
    if (RUNTIME_LOCAL) {
      apiClient
        .get<{ path: string }>(`${MCP_SERVERS_URL}/local-config`)
        .then((r) => setConfigPath(r.path))
        .catch(() => {});
    }
  }, [reload]);

  const toggleActive = useCallback(
    async (id: string, isActive: boolean) => {
      const server = connectors.find((c) => c.id === id);
      if (!server) return;
      const prev = connectors;
      // Оптимистично обновляем.
      setConnectors((list) =>
        list.map((c) => (c.id === id ? { ...c, is_active: isActive } : c)),
      );
      try {
        if (server.source === "file") {
          // Локальные серверы не в БД — выключенные храним в user.settings.
          const next = new Set(readDisabledLocal(user?.settings));
          if (isActive) next.delete(server.key);
          else next.add(server.key);
          await apiClient.patch(USER_ME_URL, {
            settings: { [DISABLED_LOCAL_KEY]: Array.from(next) },
          });
          await refreshUser();
        } else {
          await apiClient.patch(`${MCP_SERVERS_URL}/${id}`, {
            is_active: isActive,
            check_connection: false,
          });
        }
      } catch (e: any) {
        setConnectors(prev); // откат
        toast.error(e?.message || "Не удалось изменить коннектор");
      }
    },
    [connectors, user?.settings, refreshUser],
  );

  const connect = useCallback(
    async (entryId: string, inputs: Record<string, string>) => {
      const created = await apiClient.post<DbServer>(
        `${MCP_SERVERS_URL}/catalog/${encodeURIComponent(entryId)}/connect`,
        { inputs },
      );
      await reload();
      return created;
    },
    [reload],
  );

  const createCustom = useCallback(
    async (input: CreateConnectorInput) => {
      const settings: Record<string, unknown> = {};
      if (input.authType === "bearer") settings.token = input.token ?? "";
      if (input.authType === "oauth2") {
        if (input.scope?.trim()) settings.scope = input.scope.trim();
        settings.use_dcr = true;
      }
      const created = await apiClient.post<DbServer>(MCP_SERVERS_URL, {
        name: input.name?.trim() || undefined,
        url: input.url.trim(),
        auth_type: input.authType,
        settings,
        is_active: true,
        check_connection: input.authType !== "oauth2",
      });
      await reload();
      return created;
    },
    [reload],
  );

  const remove = useCallback(async (id: string) => {
    setBusyId(id);
    try {
      await apiClient.delete(`${MCP_SERVERS_URL}/${id}`);
      setConnectors((prev) => prev.filter((s) => s.id !== id));
    } catch (e: any) {
      toast.error(e?.message || "Не удалось удалить коннектор");
    } finally {
      setBusyId(null);
    }
  }, []);

  const test = useCallback(
    async (id: string) => {
      setBusyId(id);
      try {
        const res = await apiClient.post<TestResult>(
          `${MCP_SERVERS_URL}/${id}/test-connection`,
        );
        if (res.auth_required) {
          toast.info("Требуется авторизация — нажмите «Авторизоваться»");
        } else if (res.ok) {
          toast.success(
            `Подключение успешно: инструментов ${res.tool_count ?? 0}`,
          );
        } else {
          toast.error("Подключение не удалось");
        }
        await reload();
      } catch (e: any) {
        toast.error(e?.message || "Проверка подключения не удалась");
      } finally {
        setBusyId(null);
      }
    },
    [reload],
  );

  const refresh = useCallback(
    async (id: string) => {
      setBusyId(id);
      try {
        const res = await apiClient.post<{ tool_count: number }>(
          `${MCP_SERVERS_URL}/${id}/refresh-tools`,
        );
        toast.success(`Обновлено: инструментов ${res.tool_count}`);
        await reload();
      } catch (e: any) {
        toast.error(e?.message || "Не удалось обновить инструменты");
      } finally {
        setBusyId(null);
      }
    },
    [reload],
  );

  const authorize = useCallback(async (id: string) => {
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
  }, []);

  const fetchTools = useCallback(async (key: string) => {
    const res = await apiClient.get<{ tools: ToolInfo[] }>(
      `${MCP_SERVERS_URL}/tools-by-name/${encodeURIComponent(key)}`,
    );
    return res.tools;
  }, []);

  const openLocalConfig = useCallback(async () => {
    try {
      await apiClient.post(`${MCP_SERVERS_URL}/local-config/open`);
      toast.success("Файл mcp.json открыт в редакторе");
    } catch (e: any) {
      toast.error(e?.message || "Не удалось открыть файл");
    }
  }, []);

  // Колбэк OAuth от бэкенда приходит postMessage'ом из popup-окна.
  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      const data = event.data;
      if (!data || data.type !== "mcp_auth_callback") return;
      if (data.success) {
        toast.success("Авторизация прошла успешно");
        void reload();
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
  }, [reload]);

  const activeCount = connectors.filter((c) => c.is_active).length;

  return {
    connectors,
    catalog,
    moduleCatalog,
    reloadCatalog,
    loading,
    busyId,
    configPath,
    activeCount,
    reload,
    toggleActive,
    connect,
    createCustom,
    remove,
    test,
    refresh,
    authorize,
    fetchTools,
    openLocalConfig,
  };
}
