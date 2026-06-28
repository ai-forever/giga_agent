// Общие типы для нового UX «Коннекторы» (серверные MCP-серверы).
// Серверы живут в БД (source: "db") или в локальном mcp.json (source: "file").

export type AuthType = "none" | "bearer" | "oauth2";

export interface ToolInfo {
  name: string;
  description?: string;
}

export interface CatalogRequiredField {
  key: string;
  label: string;
  secret?: boolean;
  placeholder?: string;
  help_url?: string;
}

export interface CatalogEntry {
  id: string;
  name: string;
  description?: string | null;
  icon?: string | null;
  homepage?: string | null;
  categories?: string[];
  url: string;
  auth_type: AuthType | string;
  oauth_scope?: string | null;
  requires?: CatalogRequiredField[];
}

// Ответ GET /mcp/servers (БД-серверы)
export interface DbServer {
  id: string;
  name?: string | null;
  url: string;
  auth_type: AuthType;
  is_active: boolean;
  is_local: boolean;
  has_token: boolean;
  tool_count?: number | null;
  can_edit: boolean;
}

// Ответ GET /mcp/servers/local (локальный mcp.json, только RUNTIME_LOCAL)
export interface LocalServer {
  id: string;
  name: string;
  transport: string;
  url?: string | null;
  command?: string | null;
  is_local: boolean;
  is_active?: boolean;
  auth_type: string;
}

// Унифицированный коннектор для UI (db + file)
export interface UnifiedServer {
  key: string; // имя для модели, используется в tools-by-name
  id: string; // uuid (db) или name (local)
  name: string;
  url?: string | null;
  command?: string | null;
  transport?: string;
  auth_type: AuthType | string;
  is_active: boolean; // file-серверы всегда считаем активными
  is_local: boolean;
  source: "db" | "file";
  has_token?: boolean;
  tool_count?: number | null;
  can_edit?: boolean;
}

export interface CreateConnectorInput {
  name?: string;
  url: string;
  authType: AuthType;
  token?: string;
  scope?: string;
}

// --- Подключаемые нативные модули (vk, yandex_disk, github, …) -------------- //
// Приходят из GET /agent/connectors/catalog вместе с MCP-каталогом и
// рендерятся в том же гриде directory-modal.

export type ModuleAuthKind = "oauth2" | "manual_token" | "both";
export type ModuleConnStatus = "not_connected" | "connected" | "needs_reauth";

export interface ModuleManualField {
  key: string;
  label: string;
  secret: boolean;
  placeholder?: string | null;
}

export interface ModuleCatalogEntry {
  kind: "module";
  module_id: string;
  name: string;
  description?: string | null;
  icon?: string | null;
  categories: string[];
  provider_key: string;
  auth_kind: ModuleAuthKind;
  manual_fields: ModuleManualField[];
  status: ModuleConnStatus;
  enabled: boolean;
}

// Ответ GET /agent/connectors/catalog.
export interface ConnectorsCatalog {
  mcp: CatalogEntry[];
  modules: ModuleCatalogEntry[];
}

// Подобрать иконку коннектора по совпадению URL с записью каталога.
export function iconForConnector(
  connector: Pick<UnifiedServer, "url">,
  catalog: CatalogEntry[],
): string | null {
  if (!connector.url) return null;
  const entry = catalog.find((c) => c.url === connector.url);
  return entry?.icon ?? null;
}
