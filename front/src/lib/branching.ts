// Message-level branch tree.
//
// The app opens threads with `fetchStateHistory: false`, so the SDK's built-in
// branch helpers (getMessagesMetadata / branch / setBranch) are unavailable. We
// fetch a compact, deduplicated history from the backend (see `branches-api.ts`)
// and reconstruct branches here.
//
// Unlike the SDK's algorithm — which threads through every internal checkpoint
// (`__start__`, `before_model`, `model`, …) and so has to work around node-step
// noise — we collapse straight to the *messages*. Each state's message list is a
// linear path of message ids; chaining those paths yields a tree keyed by
// message id. A message position has alternatives ("branches") exactly when one
// message has more than one distinct following message across the history (an
// edit or a regeneration). This maps directly onto the switcher the UI renders
// under a message, and lets us pick the live head by recency instead of by
// checkpoint-id ordering.

import type { Message, ThreadState } from "@langchain/langgraph-sdk";

export type AnyThreadState = ThreadState<any>;
export type GetMessages = (values: any) => Message[];

export interface MessageMetadata {
  messageId: string;
  /** Oldest state whose message list contains this id (created_at / parent). */
  firstSeenState: AnyThreadState | undefined;
  /** Sibling currently on the active path at this message's fork, if forked. */
  branch: string | undefined;
  /** All sibling message ids at this fork, ordered oldest → newest. */
  branchOptions: string[] | undefined;
}

/** Empty branch selection — render/continue from the live (newest) head. */
export const HEAD_BRANCH = "";

const ROOT_ID = "$";

export interface MessageTree {
  /** parent message id (or ROOT_ID) → ordered child message ids. */
  childrenOf: Map<string, string[]>;
  /** child message id → its parent message id (or ROOT_ID). Each id has one. */
  parentOf: Map<string, string>;
  /** message id → oldest state that contains it. */
  firstStateOf: Map<string, AnyThreadState>;
  /** message id → latest created_at among states containing it (recency). */
  recencyOf: Map<string, string>;
  /** message id → message object (last writer wins; identical by id). */
  messageById: Map<string, Message>;
  hasForks: boolean;
}

/**
 * Build the message tree from compact states. States arrive newest → oldest, so
 * unconditionally overwriting `firstStateOf`/`messageById` leaves the oldest
 * occurrence; `recencyOf` keeps the newest `created_at`.
 */
export function buildMessageTree(
  states: AnyThreadState[],
  getMessages: GetMessages,
): MessageTree {
  // parent → child → earliest created_at the edge was seen (for option order).
  const edges = new Map<string, Map<string, string>>();
  const parentOf = new Map<string, string>();
  const firstStateOf = new Map<string, AnyThreadState>();
  const recencyOf = new Map<string, string>();
  const messageById = new Map<string, Message>();

  for (const state of states) {
    const ts = state.created_at ?? "";
    let prev = ROOT_ID;
    for (const message of getMessages(state.values)) {
      const id = message?.id != null ? String(message.id) : null;
      if (id == null) continue;
      let children = edges.get(prev);
      if (!children) {
        children = new Map();
        edges.set(prev, children);
      }
      const seenTs = children.get(id);
      if (seenTs == null || (ts && ts < seenTs)) children.set(id, ts);
      if (!parentOf.has(id)) parentOf.set(id, prev);
      firstStateOf.set(id, state);
      messageById.set(id, message);
      const recency = recencyOf.get(id);
      if (recency == null || (ts && ts > recency)) recencyOf.set(id, ts);
      prev = id;
    }
  }

  const childrenOf = new Map<string, string[]>();
  let hasForks = false;
  for (const [parent, children] of edges) {
    const ordered = [...children.entries()]
      .sort(
        (a, b) => (a[1] || "").localeCompare(b[1] || "") || a[0].localeCompare(b[0]),
      )
      .map(([id]) => id);
    childrenOf.set(parent, ordered);
    if (ordered.length > 1) hasForks = true;
  }

  return { childrenOf, parentOf, firstStateOf, recencyOf, messageById, hasForks };
}

/** Default child at a fork: the one with the most recent activity in its path. */
export function defaultChildOf(
  tree: MessageTree,
  parent: string,
): string | undefined {
  const children = tree.childrenOf.get(parent);
  if (!children?.length) return undefined;
  let best = children[0];
  let bestTs = tree.recencyOf.get(best) ?? "";
  for (const child of children) {
    const ts = tree.recencyOf.get(child) ?? "";
    if (ts > bestTs) {
      best = child;
      bestTs = ts;
    }
  }
  return best;
}

/**
 * Walk from the root following `selection` overrides, defaulting to the newest
 * child at each unselected fork. Returns the ordered message ids of the branch.
 */
export function getActivePath(
  tree: MessageTree,
  selection: Map<string, string>,
): string[] {
  const path: string[] = [];
  const visited = new Set<string>();
  let current = ROOT_ID;
  while (true) {
    const children = tree.childrenOf.get(current);
    if (!children?.length) break;
    let next = selection.get(current);
    if (next == null || !children.includes(next)) next = defaultChildOf(tree, current);
    if (next == null || visited.has(next)) break;
    visited.add(next);
    path.push(next);
    current = next;
  }
  return path;
}

/** Branch info for a single message position (undefined when not forked). */
export function getBranchInfo(
  tree: MessageTree,
  selection: Map<string, string>,
  messageId: string,
): { branch: string | undefined; branchOptions: string[] | undefined } {
  const parent = tree.parentOf.get(messageId);
  if (parent == null) return { branch: undefined, branchOptions: undefined };
  const options = tree.childrenOf.get(parent);
  if (!options || options.length <= 1)
    return { branch: undefined, branchOptions: undefined };
  const active = selection.get(parent) ?? defaultChildOf(tree, parent);
  return { branch: active, branchOptions: options };
}

export function getMessageMetadata(
  tree: MessageTree,
  selection: Map<string, string>,
  messageId: string,
): MessageMetadata {
  const { branch, branchOptions } = getBranchInfo(tree, selection, messageId);
  return {
    messageId,
    firstSeenState: tree.firstStateOf.get(messageId),
    branch,
    branchOptions,
  };
}

/**
 * State whose message list is exactly `path` (same length, same tip). Prefers a
 * completed leaf (`next: []`) over an intermediate node step. Used to resolve
 * the checkpoint to continue/fork a viewed branch from.
 */
export function findTipState(
  states: AnyThreadState[],
  path: string[],
  getMessages: GetMessages,
): AnyThreadState | undefined {
  const lastId = path.at(-1);
  if (lastId == null) return undefined;
  let fallback: AnyThreadState | undefined;
  for (const state of states) {
    const messages = getMessages(state.values);
    if (messages.length !== path.length) continue;
    if (String(messages.at(-1)?.id) !== lastId) continue;
    if ((state.next?.length ?? 0) === 0) return state;
    fallback ??= state;
  }
  return fallback;
}

export function arraysEqual(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
  return true;
}
