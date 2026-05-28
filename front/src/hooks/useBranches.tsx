// Custom branch store. The app loads threads with `fetchStateHistory: false`,
// so the SDK can't reconstruct branches. This provider lazily fetches a compact
// branch tree from the backend and exposes SDK-compatible branch helpers
// (getMessagesMetadata / getHistory) plus branch viewing + switching, so the
// rest of the UI keeps working without the heavy history download.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MutableRefObject,
  type ReactNode,
} from "react";
import type { Message } from "@langchain/langgraph-sdk";
import { useAuth } from "@/components/providers/auth.tsx";
import {
  cancelBranchTree,
  fetchBranchTree,
  type BranchTree,
} from "@/lib/branches-api";
import {
  getBranchContext,
  getMessagesMetadataMap,
  type AnyThreadState,
  type MessageMetadata,
} from "@/lib/branching";

const HISTORY_LIMIT = 1000;

const getMessages = (values: any): Message[] => values?.messages ?? [];

function computeMetadata(
  states: AnyThreadState[],
  activeBranch: string,
  initialValues: any,
): MessageMetadata[] {
  const branchContext = getBranchContext(activeBranch, states);
  return getMessagesMetadataMap({
    branchContext,
    history: states,
    getMessages,
    initialValues,
  });
}

// --- Incremental checkpoint-event ingestion ---------------------------------
// The `onCheckpointEvent` stream callback lets us grow the branch tree as a run
// streams instead of refetching the whole compact history after every request.
// The runtime payload shape isn't strictly typed, so read every known location:
// langgraph's `checkpoints` stream mode sends a StateSnapshot-like object
// (`{ values, next, config, parent_config, checkpoint, ... }`), while the v2
// envelope is lighter (`{ id, parent_id }`). We map either onto an
// `AnyThreadState` matching what `fetchBranchTree` rehydrates from the backend.

type ConfigurableSource = {
  configurable?: {
    checkpoint_id?: string;
    thread_id?: string;
    checkpoint_ns?: string;
  };
};

function readCheckpointId(data: any): string | undefined {
  return (
    data?.checkpoint?.checkpoint_id ??
    (data?.config as ConfigurableSource | undefined)?.configurable
      ?.checkpoint_id ??
    data?.id ??
    undefined
  );
}

function readParentId(data: any): string | undefined {
  return (
    data?.parent_checkpoint?.checkpoint_id ??
    (data?.parent_config as ConfigurableSource | undefined)?.configurable
      ?.checkpoint_id ??
    data?.parent_id ??
    undefined
  );
}

function readThreadId(data: any, fallback?: string): string | undefined {
  return (
    data?.checkpoint?.thread_id ??
    (data?.config as ConfigurableSource | undefined)?.configurable?.thread_id ??
    fallback ??
    undefined
  );
}

function readCheckpointNs(data: any): string {
  return (
    data?.checkpoint?.checkpoint_ns ??
    (data?.config as ConfigurableSource | undefined)?.configurable
      ?.checkpoint_ns ??
    ""
  );
}

// has_forks mirrors the backend: a parent checkpoint with more than one distinct
// child checkpoint is a fork point.
function computeHasForks(states: AnyThreadState[]): boolean {
  const childrenByParent = new Map<string, Set<string>>();
  for (const st of states) {
    const childId = st.checkpoint?.checkpoint_id;
    if (!childId) continue;
    const parentId = st.parent_checkpoint?.checkpoint_id ?? "$";
    let set = childrenByParent.get(parentId);
    if (!set) {
      set = new Set<string>();
      childrenByParent.set(parentId, set);
    }
    set.add(childId);
  }
  for (const set of childrenByParent.values()) {
    if (set.size > 1) return true;
  }
  return false;
}

export interface MessageBranchInfo {
  meta: MessageMetadata | undefined;
  branch: string | undefined;
  branchOptions: string[] | undefined;
  index: number;
  count: number;
}

export interface ForkData {
  meta: MessageMetadata | undefined;
  history: AnyThreadState[];
}

interface BranchesContextValue {
  hasForks: boolean;
  loading: boolean;
  /** True only while the first branch history for the current thread loads. */
  initialLoading: boolean;
  activeBranch: string;
  isViewingNonHead: boolean;
  /** Messages of the active branch (head when activeBranch is ""). */
  viewedMessages: Message[];
  /** What should actually render: viewed branch when non-head, else live head. */
  activeMessages: Message[];
  activeCheckpoint: AnyThreadState["checkpoint"] | undefined;
  ensureTree: () => Promise<BranchTree | null>;
  reloadTree: () => Promise<BranchTree | null>;
  switchBranch: (branch: string) => void;
  getMessageBranchInfo: (message: Message) => MessageBranchInfo;
  /** Drop-in replacement for thread.getMessagesMetadata (render-time, reactive). */
  getMessagesMetadata: (message: Message) => MessageMetadata | undefined;
  /** Drop-in replacement for thread.history / safeThreadHistory (always fresh). */
  getHistory: () => AnyThreadState[];
  /** Ensure the tree is loaded, then resolve fresh fork metadata + history. */
  resolveForkData: (message: Message) => Promise<ForkData>;
}

const EMPTY_INFO: MessageBranchInfo = {
  meta: undefined,
  branch: undefined,
  branchOptions: undefined,
  index: -1,
  count: 0,
};

const defaultValue: BranchesContextValue = {
  hasForks: false,
  loading: false,
  initialLoading: false,
  activeBranch: "",
  isViewingNonHead: false,
  viewedMessages: [],
  activeMessages: [],
  activeCheckpoint: undefined,
  ensureTree: async () => null,
  reloadTree: async () => null,
  switchBranch: () => {},
  getMessageBranchInfo: () => EMPTY_INFO,
  getMessagesMetadata: () => undefined,
  getHistory: () => [],
  resolveForkData: async () => ({ meta: undefined, history: [] }),
};

const BranchesContext = createContext<BranchesContextValue>(defaultValue);

export function useBranches(): BranchesContextValue {
  return useContext(BranchesContext);
}

interface BranchesProviderProps {
  thread: any;
  threadId: string | null | undefined;
  /**
   * True when this thread was created in the current session (first messages
   * are happening here). For such threads we never fetch the compact history —
   * the branch tree is built incrementally from streamed checkpoint events.
   */
  isNewThread?: boolean;
  /**
   * Filled by the provider with its `appendCheckpointEvent` handler so the
   * owner of `useStream` (Chat) can feed `onCheckpointEvent` payloads in
   * without the provider needing to live above the stream.
   */
  checkpointEventRef?: MutableRefObject<((data: any) => void) | null>;
  children: ReactNode;
}

export function BranchesProvider({
  thread,
  threadId,
  isNewThread = false,
  checkpointEventRef,
  children,
}: BranchesProviderProps) {
  const { token } = useAuth();
  const [tree, setTree] = useState<BranchTree | null>(null);
  const [loading, setLoading] = useState(false);
  const [activeBranch, setActiveBranch] = useState("");

  // Refs mirror state so async handlers (edit/refresh) read fresh values after
  // an await, not the stale closure captured at render time.
  const treeRef = useRef<BranchTree | null>(null);
  const activeBranchRef = useRef("");
  activeBranchRef.current = activeBranch;
  const tokenRef = useRef(token);
  tokenRef.current = token;
  const currentThreadIdRef = useRef(threadId);
  currentThreadIdRef.current = threadId;

  const loadedThreadIdRef = useRef<string | null>(null);
  const inFlightRef = useRef<Promise<BranchTree | null> | null>(null);
  // Newest checkpoint id we've seen — used as the parent fallback for an
  // incoming checkpoint event when the payload omits its own parent link
  // (correct for linear appends, which continue from the current head).
  const lastCheckpointIdRef = useRef<string | null>(null);

  // Reset everything when the thread changes.
  useEffect(() => {
    // Abort the previous thread's in-flight compact request so it doesn't keep
    // running after we leave it (e.g. switching to a new chat starts no request
    // that would otherwise supersede it).
    cancelBranchTree();
    setTree(null);
    treeRef.current = null;
    setActiveBranch("");
    loadedThreadIdRef.current = null;
    inFlightRef.current = null;
    lastCheckpointIdRef.current = null;
  }, [threadId]);

  const load = useCallback(
    (force: boolean): Promise<BranchTree | null> => {
      if (!threadId) return Promise.resolve(null);
      if (!force && loadedThreadIdRef.current === threadId) {
        return Promise.resolve(treeRef.current);
      }
      if (!force && inFlightRef.current) return inFlightRef.current;
      const targetThreadId = threadId;
      setLoading(true);
      const promise = (async () => {
        try {
          const next = await fetchBranchTree(targetThreadId, tokenRef.current, {
            limit: HISTORY_LIMIT,
          });
          // Drop the result if the user navigated to another thread meanwhile.
          if (targetThreadId !== currentThreadIdRef.current)
            return treeRef.current;
          treeRef.current = next;
          loadedThreadIdRef.current = targetThreadId;
          // States come newest→oldest; seed the parent fallback with the head.
          lastCheckpointIdRef.current =
            next.states[0]?.checkpoint?.checkpoint_id ?? null;
          setTree(next);
          return next;
        } catch {
          // Endpoint missing / error: leave tree empty → switchers hidden,
          // edit/refresh fall back to their existing remote path.
          return treeRef.current;
        } finally {
          setLoading(false);
          inFlightRef.current = null;
        }
      })();
      inFlightRef.current = promise;
      return promise;
    },
    [threadId],
  );

  const ensureTree = useCallback(() => load(false), [load]);
  const reloadTree = useCallback(() => load(true), [load]);

  const switchBranch = useCallback((branch: string) => {
    setActiveBranch(branch);
  }, []);

  // Load the compact tree once when a thread first opens. Subsequent updates
  // arrive incrementally via `appendCheckpointEvent`, so we never refetch the
  // full history on each request.
  useEffect(() => {
    if (!threadId) return;
    if (isNewThread) {
      // New thread: don't fetch — its tree is built from streamed checkpoint
      // events. Seed an empty tree and mark it loaded so that even after the
      // "new" flag clears (when its first load settles), ensureTree/
      // resolveForkData short-circuit instead of hitting the backend.
      if (loadedThreadIdRef.current !== threadId) {
        const empty: BranchTree = { states: [], hasForks: false };
        treeRef.current = empty;
        setTree(empty);
        loadedThreadIdRef.current = threadId;
      }
      return;
    }
    void ensureTree();
  }, [threadId, isNewThread, ensureTree]);

  // Merge a single streamed checkpoint into the in-memory tree, deduping by
  // checkpoint id. New checkpoints are newer than everything we hold, so they
  // prepend (states stay newest→oldest, which `findLast` relies on). Wired to
  // `onCheckpointEvent` by Chat via `checkpointEventRef`.
  const appendCheckpointEvent = useCallback((data: any) => {
    if (!data || typeof data !== "object") return;
    const checkpointId = readCheckpointId(data);
    if (!checkpointId) return;

    const threadIdValue = readThreadId(
      data,
      currentThreadIdRef.current ?? undefined,
    );
    const checkpointNs = readCheckpointNs(data);
    const parentId =
      readParentId(data) ?? lastCheckpointIdRef.current ?? undefined;
    const messages: any[] = Array.isArray(data?.values?.messages)
      ? data.values.messages
      : [];

    const newState = {
      values: { messages },
      next: Array.isArray(data?.next) ? data.next : [],
      checkpoint: {
        checkpoint_id: checkpointId,
        thread_id: threadIdValue,
        checkpoint_ns: checkpointNs,
      },
      parent_checkpoint: parentId
        ? {
            checkpoint_id: parentId,
            thread_id: threadIdValue,
            checkpoint_ns: checkpointNs,
          }
        : null,
      metadata: {},
      created_at: data?.created_at ?? null,
      tasks: [],
    } as unknown as AnyThreadState;

    lastCheckpointIdRef.current = checkpointId;

    const prevStates = treeRef.current?.states ?? [];
    const existingIndex = prevStates.findIndex(
      (s) => s.checkpoint?.checkpoint_id === checkpointId,
    );

    let nextStates: AnyThreadState[];
    if (existingIndex >= 0) {
      // Re-emitted checkpoint: keep prior messages if this event carries none.
      const existing = prevStates[existingIndex];
      const existingMessages = getMessages(existing?.values);
      const mergedMessages = messages.length > 0 ? messages : existingMessages;
      nextStates = prevStates.slice();
      nextStates[existingIndex] = {
        ...newState,
        values: { messages: mergedMessages },
      } as AnyThreadState;
    } else {
      nextStates = [newState, ...prevStates];
    }

    const next: BranchTree = {
      states: nextStates,
      hasForks: computeHasForks(nextStates),
    };
    treeRef.current = next;
    setTree(next);
  }, []);

  // Expose the handler to Chat's `onCheckpointEvent` without lifting the
  // provider above `useStream`.
  useEffect(() => {
    if (!checkpointEventRef) return;
    checkpointEventRef.current = appendCheckpointEvent;
    return () => {
      checkpointEventRef.current = null;
    };
  }, [checkpointEventRef, appendCheckpointEvent]);

  const states = tree?.states ?? [];

  const branchContext = useMemo(
    () => getBranchContext(activeBranch, states),
    [activeBranch, states],
  );

  // Reactive metadata for render-time consumers (BranchSwitcher, AgentRun).
  const metaById = useMemo(() => {
    const initialValues = thread?.messages
      ? { ...(thread?.values ?? {}), messages: thread.messages }
      : thread?.values;
    const list = getMessagesMetadataMap({
      branchContext,
      history: states,
      getMessages,
      initialValues,
    });
    const map = new Map<string, MessageMetadata>();
    for (const m of list) map.set(m.messageId, m);
    return map;
  }, [branchContext, states, thread?.messages, thread?.values]);

  const getMessagesMetadata = useCallback(
    (message: Message): MessageMetadata | undefined => {
      if (message?.id == null) return undefined;
      return metaById.get(String(message.id));
    },
    [metaById],
  );

  const getMessageBranchInfo = useCallback(
    (message: Message): MessageBranchInfo => {
      const meta = getMessagesMetadata(message);
      const branch = meta?.branch;
      const branchOptions = meta?.branchOptions;
      const index =
        branch && branchOptions ? branchOptions.indexOf(branch) : -1;
      return {
        meta,
        branch,
        branchOptions,
        index,
        count: branchOptions?.length ?? 0,
      };
    },
    [getMessagesMetadata],
  );

  const getHistory = useCallback(() => treeRef.current?.states ?? [], []);

  const resolveForkData = useCallback(
    async (message: Message): Promise<ForkData> => {
      const loaded = await load(false);
      const freshStates = loaded?.states ?? treeRef.current?.states ?? [];
      const initialValues = thread?.messages
        ? { ...(thread?.values ?? {}), messages: thread.messages }
        : thread?.values;
      const list = computeMetadata(
        freshStates,
        activeBranchRef.current,
        initialValues,
      );
      const meta =
        message?.id != null
          ? list.find((m) => m.messageId === String(message.id))
          : undefined;
      return { meta, history: freshStates };
    },
    [load, thread?.messages, thread?.values],
  );

  const isViewingNonHead = !!tree && activeBranch !== "";

  const viewedMessages = useMemo(
    () => getMessages(branchContext.threadHead?.values ?? thread?.values),
    [branchContext, thread?.values],
  );

  const activeMessages = isViewingNonHead
    ? viewedMessages
    : (thread?.messages ?? []);

  const activeCheckpoint = branchContext.threadHead?.checkpoint;

  const value: BranchesContextValue = {
    hasForks: tree?.hasForks ?? false,
    loading,
    initialLoading: loading && !tree,
    activeBranch,
    isViewingNonHead,
    viewedMessages,
    activeMessages,
    activeCheckpoint,
    ensureTree,
    reloadTree,
    switchBranch,
    getMessageBranchInfo,
    getMessagesMetadata,
    getHistory,
    resolveForkData,
  };

  return (
    <BranchesContext.Provider value={value}>
      {children}
    </BranchesContext.Provider>
  );
}
