import { API_AGENT_PREFIX } from "@/config.ts";
import { apiClient } from "@/lib/api-client";
import type { Activity } from "@/interfaces";

// Ручка активности экспериментального режима монтируется под
// /agent/experimental (см. ExperimentalModule.get_api_router).
export const ACTIVITY_API_PREFIX = `${API_AGENT_PREFIX}/experimental`;

/** Живой лог активности треда (для панели во время активного рана). */
export const getActivity = (
  threadId: string,
  options?: { signal?: AbortSignal },
): Promise<Activity> =>
  apiClient.get<Activity>(`${ACTIVITY_API_PREFIX}/activity/${threadId}`, {
    signal: options?.signal,
    // Поллинг: сетевые сбои не показываем тостом.
    showError: false,
  });

/**
 * Удалить экспериментальный тред вместе со скрытым inner-тредом.
 *
 * Прямое `threads.delete` через SDK удалило бы только внешний тред, оставив
 * inner-тред реального агента осиротевшим. Эта ручка удаляет оба (см.
 * ExperimentalModule / api.delete_thread).
 */
export const deleteExperimentalThread = (threadId: string): Promise<void> =>
  apiClient.delete<void>(`${ACTIVITY_API_PREFIX}/thread/${threadId}`);
