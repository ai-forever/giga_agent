// Shared types for settings-page forms

export type ConnectorType = "openai" | "gigachat" | "tavily";

/** GigaChat API type: prod/preview use credentials; dev uses base_url + username + password */
export type GigaChatApiType = "prod" | "preview" | "dev";

/** GigaChat scope (authorization scope) */
export type GigaChatScope = "GIGACHAT_API_PERS" | "GIGACHAT_API_B2B" | "GIGACHAT_API_CORP";

export interface ConnectorSettings {
  base_url?: string;
  api_key?: string;
  gigachat_api_type?: GigaChatApiType;
  gigachat_credentials?: string;
  gigachat_username?: string;
  gigachat_password?: string;
  gigachat_scope?: string;
  extra?: Record<string, unknown>;
}

export interface LLMSettings {
  temperature?: number;
  max_tokens?: number;
  top_p?: number;
  extra?: Record<string, unknown>;
}

export interface ConnectorResponse {
  id: string;
  owner_id: string;
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
  anyOf?: { type?: string }[];
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
