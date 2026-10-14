import { API_AGENT_PREFIX } from "@/config";
import { apiClient } from "@/lib/api-client";

export type ToolEffect = "read" | "write" | "destructive";

export type AgentSkillRequirement = {
  name: string;
  source?: string | null;
  ref?: string | null;
};

export type AgentDefinition = {
  ref: string;
  id: string;
  source: "builtin" | "custom";
  name: string;
  description: string;
  prompt: string;
  tags: string[];
  icon?: string | null;
  // Legacy manifest fields. Custom profiles use the capability fields below.
  skills?: AgentSkillRequirement[];
  modules: string[];
  connectors?: string[];
  tools?: { default: "read"; allow: string[]; deny: string[] };
  examples: string[];
  skill_names?: string[];
  mcp_server_ids?: string[];
  allowed_tool_effects?: ToolEffect[];
  enabled: boolean;
  readiness: "ready" | "needs_setup";
  missing: { kind: string; id: string }[];
  profile_id?: string | null;
  llm_id?: string | null;
};

export type AgentDraft = {
  name: string;
  description: string;
  prompt: string;
  modules: string[];
  mcp_server_ids: string[];
  skill_names: string[];
  allowed_tool_effects: ToolEffect[];
  llm_id: string | null;
  is_enabled: boolean;
};

export type AgentEditorOptions = {
  modules: { id: string; label: string; description: string; icon: string }[];
  mcp_servers: { id: string; name: string }[];
  skills: { name: string; description: string; source_type: string }[];
  llms: { id: string; name: string; model_id: string }[];
};

const PREFIX = `${API_AGENT_PREFIX}/agents`;
const ref = (value: string) => encodeURIComponent(value);

export const listAgents = () => apiClient.get<AgentDefinition[]>(PREFIX);
export const getAgentEditorOptions = () =>
  apiClient.get<AgentEditorOptions>(`${PREFIX}/editor-options`);
export const createAgent = (draft: AgentDraft) =>
  apiClient.post<AgentDefinition>(PREFIX, draft);
export const updateAgent = (agentRef: string, draft: Partial<AgentDraft>) =>
  apiClient.patch<AgentDefinition>(`${PREFIX}/${ref(agentRef)}`, draft);
export const deleteAgent = (agentRef: string) =>
  apiClient.delete<void>(`${PREFIX}/${ref(agentRef)}`);
export const cloneAgent = (agentRef: string) =>
  apiClient.post<AgentDefinition>(`${PREFIX}/${ref(agentRef)}/clone`);
export const setAgentEnabled = (agentRef: string, enabled: boolean) =>
  apiClient.put<AgentDefinition>(`${PREFIX}/${ref(agentRef)}/enabled`, {
    enabled,
  });
export const installAgentSkills = (agentRef: string) =>
  apiClient.post<{ installed: unknown[] }>(
    `${PREFIX}/${ref(agentRef)}/install-skills`,
    { confirmed: true },
  );

// This endpoint remains for legacy built-in manifest setup only.
export const updateAgentBindings = (
  agentRef: string,
  payload: {
    llm_id: string | null;
    skills: Record<string, string>;
    connectors: Record<string, string>;
  },
) =>
  apiClient.put<AgentDefinition>(
    `${PREFIX}/${ref(agentRef)}/bindings`,
    payload,
  );
