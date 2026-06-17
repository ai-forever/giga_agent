import { API_AGENT_PREFIX } from "@/config.ts";
import { apiClient } from "@/lib/api-client";

export const MEMORY_API_PREFIX = `${API_AGENT_PREFIX}/memory`;

export const ABOUT_PATH = "/memories/ABOUT.md";

export type MemoryFileSummary = {
  id: string;
  path: string;
  tag: string | null;
  description: string | null;
  content_hash: string;
  indexed: boolean;
  updated_at: string | null;
};

export type MemoryFileDetails = MemoryFileSummary & {
  content: string;
  body: string;
};

export const listMemories = (
  tag?: string,
  options?: { signal?: AbortSignal },
): Promise<MemoryFileSummary[]> => {
  const url = tag
    ? `${MEMORY_API_PREFIX}?tag=${encodeURIComponent(tag)}`
    : MEMORY_API_PREFIX;
  return apiClient.get<MemoryFileSummary[]>(url, {
    showError: false,
    signal: options?.signal,
  });
};

export const getMemory = (
  memoryId: string,
  options?: { signal?: AbortSignal },
): Promise<MemoryFileDetails> =>
  apiClient.get<MemoryFileDetails>(`${MEMORY_API_PREFIX}/${memoryId}`, {
    showError: false,
    signal: options?.signal,
  });

export const getMemoryByPath = (
  path: string,
  options?: { signal?: AbortSignal },
): Promise<MemoryFileDetails> =>
  apiClient.get<MemoryFileDetails>(
    `${MEMORY_API_PREFIX}/by-path?path=${encodeURIComponent(path)}`,
    { showError: false, signal: options?.signal },
  );

export const upsertMemoryByPath = (
  path: string,
  content: string,
): Promise<MemoryFileDetails> =>
  apiClient.put<MemoryFileDetails>(
    `${MEMORY_API_PREFIX}/by-path`,
    { path, content },
    { showError: false },
  );

export const updateMemory = (
  memoryId: string,
  content: string,
): Promise<MemoryFileDetails> =>
  apiClient.put<MemoryFileDetails>(
    `${MEMORY_API_PREFIX}/${memoryId}`,
    { content },
    { showError: false },
  );

export const deleteMemory = (memoryId: string): Promise<void> =>
  apiClient.delete<void>(`${MEMORY_API_PREFIX}/${memoryId}`, {
    showError: false,
  });
