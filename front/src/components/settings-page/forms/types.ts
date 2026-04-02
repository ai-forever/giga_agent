// Shared types for settings-page forms

export type ConnectorType = "openai" | "gigachat" | "tavily";

/** GigaChat API type: prod uses credentials + urls; dev uses base_url + username + password */
export type GigaChatApiType = "prod" | "dev";

/** GigaChat scope (authorization scope) */
export type GigaChatScope =
  | "GIGACHAT_API_PERS"
  | "GIGACHAT_API_B2B"
  | "GIGACHAT_API_CORP";

export interface ConnectorSettings {
  base_url?: string;
  api_key?: string;
  gigachat_api_type?: GigaChatApiType;
  gigachat_credentials?: string;
  gigachat_username?: string;
  gigachat_password?: string;
  gigachat_scope?: string;
  gigachat_base_url?: string;
  gigachat_auth_url?: string;
  extra?: Record<string, unknown>;
}

export interface LLMSettings {
  [key: string]: unknown;
  temperature?: number;
  max_tokens?: number;
  top_p?: number;
  extra?: Record<string, unknown>;
}

export interface ConnectorResponse {
  id: string;
  owner_id: string;
  can_edit: boolean;
  type: string;
  name: string | null;
  settings: ConnectorSettings;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface LLMResponse {
  id: string;
  owner_id: string;
  can_edit: boolean;
  type: string;
  connector_id: string;
  model_id: string;
  name: string | null;
  parallel_calls: number;
  settings: LLMSettings;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface AvailableModel {
  id: string;
  name: string | null;
  created?: number;
  owned_by?: string;
}

export interface AvailableEmbeddingModel {
  id: string;
  name: string | null;
  created?: number;
  owned_by?: string;
}

export interface LLMTypeMeta {
  type: string;
  supported_connector_types: string[];
}

export interface EmbeddingTypeMeta {
  type: string;
  supported_connector_types: string[];
}

export interface ConnectorTypeMeta {
  type: string;
}

export interface JsonSchemaProperty {
  type?: string;
  title?: string;
  description?: string;
  default?: unknown;
  enum?: Array<string | number | boolean | null>;
  oneOf?: { const?: unknown; title?: string; type?: string }[];
  anyOf?: {
    type?: string;
    const?: unknown;
    title?: string;
    enum?: unknown[];
  }[];
}

export interface JsonSchema {
  properties?: Record<string, JsonSchemaProperty>;
  required?: string[];
}

export interface LLMFormData {
  connector_id?: string;
  llm_type: string;
  model_id: string;
  llm_name?: string;
  llm_settings: LLMSettings;
  is_active: boolean;
}

export type EmbeddingSettings = Record<string, unknown>;

export interface EmbeddingResponse {
  id: string;
  owner_id: string;
  can_edit: boolean;
  type: string;
  connector_id: string;
  model_id: string;
  name: string | null;
  settings: EmbeddingSettings;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface ImageGeneratorResponse {
  id: string;
  owner_id: string;
  can_edit: boolean;
  type: string;
  name: string | null;
  settings: Record<string, unknown>;
  connector_id: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface ImageGeneratorTypeMeta {
  type: string;
  supported_connector_types: string[];
  requires_connector: boolean;
}

export interface SearchEngineResponse {
  id: string;
  owner_id: string;
  can_edit: boolean;
  type: string;
  name: string | null;
  settings: Record<string, unknown>;
  connector_id: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface SearchEngineTypeMeta {
  type: string;
  supported_connector_types: string[];
  requires_connector: boolean;
}

export type ChannelSettings = Record<string, unknown>;

export interface ChannelBotResponse {
  id: string;
  user_id: string;
  channel_type: string;
  bot_username: string | null;
  settings: ChannelSettings;
  is_enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface ChannelContactResponse {
  id: string;
  bot_id: string;
  external_chat_id: string;
  external_user_id: string | null;
  chat_type: string | null;
  chat_title: string | null;
  username: string | null;
  first_name: string | null;
  last_name: string | null;
  is_approved: boolean;
  created_at: string;
  updated_at: string;
}

export interface ChannelTypeMeta {
  type: string;
}

export type PermissionResourceType =
  | "connector"
  | "llm"
  | "embedding"
  | "image_generator"
  | "search_engine"
  | "sandbox"
  | "rag_collection";

export interface ResourcePermissionsDraft {
  read_user_ids: string[];
  read_group_ids: string[];
  public_read: boolean;
}

export const EMPTY_RESOURCE_PERMISSIONS: ResourcePermissionsDraft = {
  read_user_ids: [],
  read_group_ids: [],
  public_read: false,
};
