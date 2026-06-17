// Client for the backend's compact, deduplicated thread-history endpoint
// (giga_agent `GET /agent/threads/{id}/history/compact`). It lets us rebuild the
// branch tree without downloading the full per-checkpoint message payload.

import type { ThreadState } from "@langchain/langgraph-sdk";
import { API_AGENT_PREFIX } from "@/config.ts";
import type { AnyThreadState } from "./branching";

interface CompactState {
  checkpoint: ThreadState["checkpoint"] | null;
  parent_checkpoint: ThreadState["parent_checkpoint"] | null;
  created_at: string | null;
  next: string[];
  message_ids: string[];
}

interface CompactHistoryResponse {
  messages: Record<string, any>;
  states: CompactState[];
  has_forks: boolean;
}

export interface BranchTree {
  /** Rehydrated states in the SDK's ThreadState shape (newest → oldest). */
  states: AnyThreadState[];
  hasForks: boolean;
}

// Only one compact-history request runs at a time. A new request with the same
// params reuses the in-flight promise (no duplicate fetch); a new request with
// different params aborts the previous one before starting.
let inFlight: {
  key: string;
  controller: AbortController;
  promise: Promise<BranchTree>;
} | null = null;

function requestKey(
  threadId: string,
  opts: { limit?: number; before?: string },
): string {
  return JSON.stringify([threadId, opts.limit ?? null, opts.before ?? null]);
}

/**
 * Abort the current in-flight compact-history request, if any. Call this when
 * leaving a thread (e.g. switching to a new chat) so its request doesn't keep
 * running when nothing supersedes it.
 */
export function cancelBranchTree(): void {
  if (inFlight) {
    inFlight.controller.abort();
    inFlight = null;
  }
}

async function requestBranchTree(
  threadId: string,
  token: string | null | undefined,
  opts: { limit?: number; before?: string },
  signal: AbortSignal,
): Promise<BranchTree> {
  const params = new URLSearchParams();
  if (opts.limit != null) params.set("limit", String(opts.limit));
  if (opts.before) params.set("before", opts.before);
  const query = params.toString();
  const url = `${API_AGENT_PREFIX}/threads/${encodeURIComponent(
    threadId,
  )}/history/compact${query ? `?${query}` : ""}`;

  const res = await fetch(url, {
    method: "GET",
    credentials: "include",
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    signal,
  });
  if (!res.ok) {
    throw new Error(`compact history request failed: ${res.status}`);
  }
  const data = (await res.json()) as CompactHistoryResponse;

  const states: AnyThreadState[] = data.states.map((st) => ({
    values: {
      messages: st.message_ids
        .map((id) => data.messages[id])
        .filter((m) => m != null),
    },
    next: st.next ?? [],
    checkpoint: st.checkpoint,
    parent_checkpoint: st.parent_checkpoint,
    metadata: {},
    created_at: st.created_at,
    tasks: [],
  })) as unknown as AnyThreadState[];

  return { states, hasForks: data.has_forks };
}

/**
 * Fetch the compact branch tree for a thread and rehydrate each state's
 * `values.messages` from the shared `{id -> message}` map.
 *
 * Deduplicates and cancels concurrent calls: an identical in-flight request is
 * shared, and a differing one supersedes (aborts) the previous request.
 */
export function fetchBranchTree(
  threadId: string,
  token: string | null | undefined,
  opts: { limit?: number; before?: string } = {},
): Promise<BranchTree> {
  const key = requestKey(threadId, opts);

  // Same params already loading → reuse the existing request.
  if (inFlight && inFlight.key === key) return inFlight.promise;

  // Different params → cancel the previous request; only one runs at a time.
  if (inFlight) inFlight.controller.abort();

  const controller = new AbortController();
  const promise = requestBranchTree(threadId, token, opts, controller.signal);
  // Clear the slot once settled, unless a newer request already replaced us.
  void promise
    .catch(() => undefined)
    .finally(() => {
      if (inFlight?.controller === controller) inFlight = null;
    });

  inFlight = { key, controller, promise };
  return promise;
}
