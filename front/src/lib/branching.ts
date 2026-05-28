// Branch-tree reconstruction ported from
// @langchain/langgraph-sdk/dist/ui/branching.js.
//
// The app opens threads with `fetchStateHistory: false`, so the SDK's built-in
// branch helpers (getMessagesMetadata / branch / setBranch) are unavailable.
// We instead fetch a compact, deduplicated history from the backend (see
// `branches-api.ts`) and run the same algorithm on it here. The algorithm needs
// only `checkpoint.checkpoint_id`, `parent_checkpoint.checkpoint_id` and the
// message ids inside `values` — all present in the rehydrated compact tree.

import type { Message, ThreadState } from "@langchain/langgraph-sdk";

export type AnyThreadState = ThreadState<any>;

function findLast<T>(
  arr: T[],
  predicate: (value: T) => boolean,
): T | undefined {
  for (let i = arr.length - 1; i >= 0; i--) {
    if (predicate(arr[i])) return arr[i];
  }
  return undefined;
}

type SequenceNode = { type: "node"; value: AnyThreadState; path: string[] };
type Fork = { type: "fork"; items: Sequence[] };
export type Sequence = { type: "sequence"; items: Array<SequenceNode | Fork> };

export interface MessageMetadata {
  messageId: string;
  firstSeenState: AnyThreadState | undefined;
  branch: string | undefined;
  branchOptions: string[] | undefined;
}

export type GetMessages = (values: any) => Message[];

const PATH_SEP = ">";
const ROOT_ID = "$";

// #region debug
const DEBUG_SESSION_ID = "branch-switcher-send-from-branch-6cc880";
const DEBUG_LOG_URL = "http://localhost:8787/log";
const debugSeen = new Set<string>();
const debugLog = (
  msg: string,
  data: Record<string, unknown> = {},
  hypothesisId?: string,
) => {
  if (typeof navigator === "undefined") return;
  const payload = JSON.stringify({
    sessionId: DEBUG_SESSION_ID,
    msg,
    data,
    hypothesisId,
    loc: new Error().stack?.split("\n")[2]?.trim(),
  });
  if (navigator.sendBeacon?.(DEBUG_LOG_URL, payload)) return;
  fetch(DEBUG_LOG_URL, { method: "POST", body: payload }).catch(() => {});
};
const debugOnce = (
  key: string,
  msg: string,
  data: Record<string, unknown> = {},
  hypothesisId?: string,
) => {
  if (debugSeen.has(key)) return;
  debugSeen.add(key);
  debugLog(msg, data, hypothesisId);
};
// #endregion

function getBranchSequence(history: AnyThreadState[]): {
  rootSequence: Sequence;
  paths: string[][];
} {
  const nodeIds = new Set<string>();
  const childrenMap: Record<string, AnyThreadState[]> = {};
  if (history.length <= 1) {
    return {
      rootSequence: {
        type: "sequence",
        items: history.map((value) => ({ type: "node", value, path: [] })),
      },
      paths: [],
    };
  }
  history.forEach((state) => {
    const checkpointId = state.parent_checkpoint?.checkpoint_id ?? "$";
    childrenMap[checkpointId] ??= [];
    childrenMap[checkpointId].push(state);
    if (state.checkpoint?.checkpoint_id != null)
      nodeIds.add(state.checkpoint.checkpoint_id);
  });
  const maxId = (...ids: Array<string | undefined>) =>
    ids
      .filter((i): i is string => i != null)
      .sort((a, b) => a.localeCompare(b))
      .at(-1);
  const lastOrphanedNode =
    childrenMap.$ == null
      ? Object.keys(childrenMap)
          .filter((parentId) => !nodeIds.has(parentId))
          .map((parentId) => {
            const queue = [parentId];
            const seen = new Set<string>();
            let lastId = parentId;
            while (queue.length > 0) {
              const current = queue.shift() as string;
              if (seen.has(current)) continue;
              seen.add(current);
              const children = (childrenMap[current] ?? []).flatMap(
                (i) => i.checkpoint?.checkpoint_id ?? [],
              );
              lastId = maxId(lastId, ...children) as string;
              queue.push(...children);
            }
            return { parentId, lastId };
          })
          .sort((a, b) => a.lastId.localeCompare(b.lastId))
          .at(-1)?.parentId
      : undefined;
  if (lastOrphanedNode != null) childrenMap.$ = childrenMap[lastOrphanedNode];
  const rootSequence: Sequence = { type: "sequence", items: [] };
  const queue: Array<{ id: string; sequence: Sequence; path: string[] }> = [
    { id: "$", sequence: rootSequence, path: [] },
  ];
  const paths: string[][] = [];
  const visited = new Set<string>();
  while (queue.length > 0) {
    const task = queue.shift()!;
    if (visited.has(task.id)) continue;
    visited.add(task.id);
    const children = childrenMap[task.id];
    if (children == null || children.length === 0) continue;
    let fork: Fork | undefined;
    if (children.length > 1) {
      fork = { type: "fork", items: [] };
      task.sequence.items.push(fork);
    }
    for (const value of children) {
      const id = value.checkpoint?.checkpoint_id;
      if (id == null) continue;
      let sequence = task.sequence;
      let path = task.path;
      if (fork != null) {
        sequence = { type: "sequence", items: [] };
        fork.items.unshift(sequence);
        path = path.slice();
        path.push(id);
        paths.push(path);
      }
      sequence.items.push({ type: "node", value, path });
      queue.push({ id, sequence, path });
    }
  }
  return { rootSequence, paths };
}

function getBranchView(sequence: Sequence, paths: string[][], branch: string) {
  const path = branch.split(PATH_SEP);
  const pathMap: Record<string, string[][]> = {};
  for (const p of paths) {
    const parent = p.at(-2) ?? ROOT_ID;
    pathMap[parent] ??= [];
    pathMap[parent].unshift(p);
  }
  const history: AnyThreadState[] = [];
  const branchByCheckpoint: Record<
    string,
    { branch: string; branchOptions: string[] }
  > = {};
  const forkStack = path.slice();
  const queue: Array<SequenceNode | Fork> = [...sequence.items];
  while (queue.length > 0) {
    const item = queue.shift()!;
    if (item.type === "node") {
      history.push(item.value);
      const checkpointId = item.value.checkpoint?.checkpoint_id;
      if (checkpointId == null) continue;
      branchByCheckpoint[checkpointId] = {
        branch: item.path.join(PATH_SEP),
        branchOptions: (item.path.length > 0
          ? (pathMap[item.path.at(-2) ?? ROOT_ID] ?? [])
          : []
        ).map((p) => p.join(PATH_SEP)),
      };
    }
    if (item.type === "fork") {
      const forkId = forkStack.shift();
      const index =
        forkId != null
          ? item.items.findIndex((value) => {
              const firstItem = value.items.at(0);
              if (!firstItem || firstItem.type !== "node") return false;
              return firstItem.value.checkpoint?.checkpoint_id === forkId;
            })
          : -1;
      const nextItems = item.items.at(index)?.items ?? [];
      queue.push(...nextItems);
    }
  }
  return { history, branchByCheckpoint };
}

export interface BranchContext {
  branchTree: Sequence;
  flatHistory: AnyThreadState[];
  branchByCheckpoint: Record<
    string,
    { branch: string; branchOptions: string[] }
  >;
  threadHead: AnyThreadState | undefined;
}

export function getBranchContext(
  branch: string,
  history: AnyThreadState[],
): BranchContext {
  const { rootSequence: branchTree, paths } = getBranchSequence(history ?? []);
  const { history: flatHistory, branchByCheckpoint } = getBranchView(
    branchTree,
    paths,
    branch,
  );
  return {
    branchTree,
    flatHistory,
    branchByCheckpoint,
    threadHead: flatHistory.at(-1),
  };
}

export function getMessagesMetadataMap(options: {
  branchContext: BranchContext;
  history: AnyThreadState[];
  getMessages: GetMessages;
  initialValues?: any;
}): MessageMetadata[] {
  const { branchContext, history, getMessages } = options;
  const { branchByCheckpoint, flatHistory } = branchContext;
  const currentValues =
    branchContext.threadHead?.values ?? options.initialValues ?? {};
  const alreadyShown = new Set<string>();

  const seenIn = (states: AnyThreadState[], messageId: string | number) =>
    findLast(
      states ?? [],
      (state) =>
        state.values != null &&
        getMessages(state.values)
          .map((m, i) => m.id ?? i)
          .includes(messageId),
    );

  const result = getMessages(currentValues).map((message, idx) => {
    const messageId = message.id ?? idx;
    let firstSeenState = seenIn(history, messageId);
    let checkpointId = firstSeenState?.checkpoint?.checkpoint_id;
    // The global-oldest occurrence can sit on a sibling branch when a message
    // id is shared across forks (e.g. an edited human message keeps its id).
    // Such a checkpoint isn't in branchByCheckpoint (which only holds the
    // viewed branch), so re-resolve within the viewed branch to keep the
    // switcher on the diverging message instead of the next unique-id one.
    if (checkpointId != null && !(checkpointId in branchByCheckpoint)) {
      const scoped = seenIn(flatHistory, messageId);
      const scopedId = scoped?.checkpoint?.checkpoint_id;
      if (scopedId != null && scopedId in branchByCheckpoint) {
        firstSeenState = scoped;
        checkpointId = scopedId;
      }
    }
    let branch =
      checkpointId != null ? branchByCheckpoint[checkpointId] : undefined;
    if (!branch?.branch?.length) branch = undefined;
    const optionsShown = branch?.branchOptions?.flat().join(",");
    if (optionsShown) {
      if (alreadyShown.has(optionsShown)) branch = undefined;
      alreadyShown.add(optionsShown);
    }
    return {
      messageId: messageId.toString(),
      firstSeenState,
      branch: branch?.branch,
      branchOptions: branch?.branchOptions,
    };
  });

  const branchSummary = result
    .filter((item) => (item.branchOptions?.length ?? 0) > 1)
    .map((item) => ({
      messageId: item.messageId,
      branch: item.branch,
      branchOptions: item.branchOptions,
    }));

  debugOnce(
    `metadata-summary-${result.map((item) => item.messageId).join("|")}-${branchSummary.length}`,
    "Metadata summary after branch computation",
    {
      currentMessageIds: result.map((item) => item.messageId),
      branchSummary,
    },
    "H7",
  );

  return result;
}
