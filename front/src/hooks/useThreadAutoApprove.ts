import { useCallback, useEffect, useRef, useState } from "react";
import { useSettings } from "@/components/Settings.tsx";
import { useLangGraphClient } from "@/hooks/useLangGraphClient";
import { apiClient } from "@/lib/api-client";
import { API_AGENT_PREFIX } from "@/config";

const readMetadata = (thread: unknown): Record<string, unknown> => {
  const meta = (thread as { metadata?: Record<string, unknown> } | null)
    ?.metadata;
  return meta && typeof meta === "object" ? meta : {};
};

/**
 * Manages the "Autonomy" (auto_approve) flag at the thread level.
 *
 * - The value is stored per-thread in the thread metadata. On toggle it is written
 *   immediately via the backend `PUT /threads/{id}/auto-approve` endpoint, which
 *   merges it into thread metadata and refreshes the server-side thread_metadata
 *   cache the run middlewares read from (so a mid-run toggle is honored). The
 *   backend (ToolResultMiddleware.before_agent) also syncs it from
 *   config.configurable on submit, which covers a brand-new chat with no threadId.
 * - The global value in localStorage stays as the default for new chats.
 * - When opening an existing thread the value is read from metadata
 *   (falling back to the global default if the flag isn't stored yet).
 * - Every metadata request (read or write) goes through a single AbortController,
 *   so a new toggle / thread switch cancels the previous unfinished request and
 *   the latest write always wins.
 */
export const useThreadAutoApprove = (threadId?: string) => {
  const client = useLangGraphClient();
  const { settings, setSettings } = useSettings();

  const [autoApprove, setAutoApproveState] = useState<boolean>(
    settings.autoApprove ?? false,
  );

  // Last global default — for a new chat and threads without a stored flag.
  const globalDefaultRef = useRef(settings.autoApprove ?? false);
  globalDefaultRef.current = settings.autoApprove ?? false;

  // Controller of the in-flight metadata request (read or write). Starting a new
  // one aborts the previous so a stale request can't overwrite a fresher value.
  const abortRef = useRef<AbortController | null>(null);
  const beginRequest = useCallback(() => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    return controller;
  }, []);

  useEffect(() => {
    if (!threadId) {
      // New chat: cancel any pending request and show the last global default.
      abortRef.current?.abort();
      abortRef.current = null;
      setAutoApproveState(globalDefaultRef.current);
      return;
    }
    if (!client) return;

    const controller = beginRequest();
    void (async () => {
      try {
        const thread = await client.threads.get(threadId, {
          signal: controller.signal,
        });
        const value = readMetadata(thread).auto_approve;
        if (!controller.signal.aborted) {
          setAutoApproveState(
            typeof value === "boolean" ? value : globalDefaultRef.current,
          );
        }
      } catch {
        /* aborted or failed — keep the current value */
      }
    })();

    // Cancel the in-flight request (read or a later write) on thread switch/unmount.
    return () => {
      abortRef.current?.abort();
    };
  }, [client, threadId, beginRequest]);

  const setAutoApprove = useCallback(
    (value: boolean) => {
      setAutoApproveState(value);
      setSettings((prev) => ({ ...prev, autoApprove: value }));
      if (!threadId) return;

      // Persist via the backend endpoint (merges metadata + refreshes the cache),
      // cancelling any previous unfinished request.
      const controller = beginRequest();
      void (async () => {
        try {
          await apiClient.put(
            `${API_AGENT_PREFIX}/threads/${encodeURIComponent(
              threadId,
            )}/auto-approve`,
            { auto_approve: value },
            { signal: controller.signal, showError: false },
          );
        } catch {
          /* aborted or failed — local state still applies; backend syncs on submit */
        }
      })();
    },
    [threadId, beginRequest, setSettings],
  );

  return { autoApprove, setAutoApprove };
};
