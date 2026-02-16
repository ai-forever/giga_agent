// Types for LLM and Provider forms

export type ProviderType = "openai" | "gigachat" | "anthropic" | "ollama" | "google" | "deepseek" | "custom";

/** GigaChat API type: prod/preview use credentials; dev uses base_url + username + password */
export type GigaChatApiType = "prod" | "preview" | "dev";

/** GigaChat scope (authorization scope) */
export type GigaChatScope = "GIGACHAT_API_PERS" | "GIGACHAT_API_B2B" | "GIGACHAT_API_CORP";

export interface ProviderSettings {
  base_url?: string;
  api_key?: string;
  /** GigaChat: API type (prod | preview | dev) */
  gigachat_api_type?: GigaChatApiType;
  /** GigaChat Prod/Preview: auth token */
  gigachat_credentials?: string;
  /** GigaChat Dev: login */
  gigachat_username?: string;
  /** GigaChat Dev: password */
  gigachat_password?: string;
  /** GigaChat: authorization scope */
  gigachat_scope?: string;
  extra?: Record<string, unknown>;
}

export interface LLMSettings {
  temperature?: number;
  max_tokens?: number;
  top_p?: number;
  extra?: Record<string, unknown>;
}

export interface ProviderResponse {
  id: string;
  owner_id: string;
  type: string;
  name: string | null;
  settings: ProviderSettings;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface LLMResponse {
  id: string;
  owner_id: string;
  provider_id: string;
  model_id: string;
  name: string | null;
  settings: LLMSettings;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface LLMWithProviderResponse {
  llm: LLMResponse;
  provider: ProviderResponse;
}

export interface AvailableModel {
  id: string;
  name: string | null;
  created?: number;
  owned_by?: string;
}

export interface ProviderFormData {
  type: ProviderType;
  name?: string;
  settings: ProviderSettings;
}

export interface LLMFormData {
  provider_id?: string; // existing provider
  provider_type?: string;
  provider_name?: string;
  provider_settings?: ProviderSettings;
  model_id: string;
  llm_name?: string;
  llm_settings: LLMSettings;
  is_active: boolean;
}

export interface ImageGeneratorResponse {
  id: string;
  owner_id: string;
  type: string;
  name: string | null;
  settings: Record<string, unknown>;
  llm_provider_id: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface ImageGeneratorTypeMeta {
  type: string;
  supported_llm_provider_types: string[];
  requires_llm_provider: boolean;
}
