import { API_AGENT_PREFIX } from "@/config.ts";
import { apiClient } from "@/lib/api-client";

export const SCHEDULER_API_PREFIX = `${API_AGENT_PREFIX}/scheduler`;

export type ScheduledTaskKind = "once" | "cron";

export type DeliveryTarget = {
  bot_id: string;
  external_chat_id: string;
  external_user_id?: string | null;
};

export type ScheduledTask = {
  id: string;
  owner_id: string;
  name: string | null;
  prompt: string;
  kind: ScheduledTaskKind;
  cron: string | null;
  timezone: string | null;
  run_at: string | null;
  targets: DeliveryTarget[];
  is_enabled: boolean;
  status: string;
  last_run_at: string | null;
  last_error: string | null;
  created_at: string;
  updated_at: string;
};

export type ScheduledTaskCreate = {
  name?: string | null;
  prompt: string;
  kind: ScheduledTaskKind;
  cron?: string | null;
  timezone?: string | null;
  run_at?: string | null;
  targets?: DeliveryTarget[];
  is_enabled?: boolean;
};

export type ScheduledTaskUpdate = Partial<ScheduledTaskCreate>;

export const listScheduledTasks = (options?: {
  signal?: AbortSignal;
}): Promise<ScheduledTask[]> =>
  apiClient.get<ScheduledTask[]>(`${SCHEDULER_API_PREFIX}/tasks`, {
    signal: options?.signal,
  });

export const getScheduledTask = (
  taskId: string,
  options?: { signal?: AbortSignal },
): Promise<ScheduledTask> =>
  apiClient.get<ScheduledTask>(`${SCHEDULER_API_PREFIX}/tasks/${taskId}`, {
    showError: false,
    signal: options?.signal,
  });

export const createScheduledTask = (
  payload: ScheduledTaskCreate,
): Promise<ScheduledTask> =>
  apiClient.post<ScheduledTask>(`${SCHEDULER_API_PREFIX}/tasks`, payload);

export const updateScheduledTask = (
  taskId: string,
  payload: ScheduledTaskUpdate,
): Promise<ScheduledTask> =>
  apiClient.patch<ScheduledTask>(
    `${SCHEDULER_API_PREFIX}/tasks/${taskId}`,
    payload,
  );

export const deleteScheduledTask = (taskId: string): Promise<void> =>
  apiClient.delete<void>(`${SCHEDULER_API_PREFIX}/tasks/${taskId}`);

export const runScheduledTask = (taskId: string): Promise<unknown> =>
  apiClient.post<unknown>(`${SCHEDULER_API_PREFIX}/tasks/${taskId}/run`);
