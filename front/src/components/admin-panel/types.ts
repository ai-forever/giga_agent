export type AdminUser = {
  id: string;
  email: string;
  first_name: string | null;
  last_name: string | null;
  is_active: boolean;
  is_superuser: boolean;
  settings: Record<string, unknown> | null;
  secrets: Record<string, unknown> | null;
  llm_id: string | null;
  fast_llm_id: string | null;
  embedding_id: string | null;
  sandbox_provider_id: string | null;
  image_generator_id: string | null;
  search_engine_id: string | null;
  created_at: string;
  updated_at: string;
};

export type GroupMember = {
  id: string;
  email: string;
  first_name: string | null;
  last_name: string | null;
  is_active: boolean;
  is_superuser: boolean;
};

export type AdminGroup = {
  id: string;
  owner_id: string;
  name: string;
  description: string | null;
  data: Record<string, unknown> | null;
  permissions: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
};
