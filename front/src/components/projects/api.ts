import { API_AGENT_PREFIX } from "@/config.ts";
import { apiClient } from "@/lib/api-client";

export const PROJECTS_API_PREFIX = `${API_AGENT_PREFIX}/projects`;

export type Project = {
  id: string;
  owner_id: string;
  name: string;
  description: string | null;
  instructions: string | null;
  collection_id: string | null;
  created_at: string;
  updated_at: string;
};

export type ProjectCreate = {
  name: string;
  description?: string | null;
  instructions?: string | null;
};

export type ProjectUpdate = {
  name?: string;
  description?: string | null;
  instructions?: string | null;
};

export const listProjects = (options?: {
  signal?: AbortSignal;
}): Promise<Project[]> =>
  apiClient.get<Project[]>(`${PROJECTS_API_PREFIX}/`, {
    showError: false,
    signal: options?.signal,
  });

export const getProject = (
  projectId: string,
  options?: { signal?: AbortSignal },
): Promise<Project> =>
  apiClient.get<Project>(`${PROJECTS_API_PREFIX}/${projectId}`, {
    showError: false,
    signal: options?.signal,
  });

export const createProject = (payload: ProjectCreate): Promise<Project> =>
  apiClient.post<Project>(`${PROJECTS_API_PREFIX}/`, payload, {
    showError: false,
  });

export const updateProject = (
  projectId: string,
  payload: ProjectUpdate,
): Promise<Project> =>
  apiClient.patch<Project>(`${PROJECTS_API_PREFIX}/${projectId}`, payload, {
    showError: false,
  });

export const deleteProject = (projectId: string): Promise<void> =>
  apiClient.delete<void>(`${PROJECTS_API_PREFIX}/${projectId}`, {
    showError: false,
  });
