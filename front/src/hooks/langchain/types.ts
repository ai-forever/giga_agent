import {
  Command,
  DisconnectMode,
  Durability,
  MultitaskStrategy,
  OnCompletionBehavior,
} from "@langchain/langgraph-sdk/dist/types";
import {
  Checkpoint,
  Config,
  Metadata,
  StreamMode,
} from "@langchain/langgraph-sdk";

type ConfigWithConfigurable<ConfigurableType extends Record<string, unknown>> =
  Config & { configurable?: ConfigurableType };

export interface SubmitOptions<
  StateType extends Record<string, unknown> = Record<string, unknown>,
  ContextType extends Record<string, unknown> = Record<string, unknown>,
> {
  config?: ConfigWithConfigurable<ContextType>;
  context?: ContextType;
  checkpoint?: Omit<Checkpoint, "thread_id"> | null;
  command?: Command;
  interruptBefore?: "*" | string[];
  interruptAfter?: "*" | string[];
  metadata?: Metadata;
  multitaskStrategy?: MultitaskStrategy;
  onCompletion?: OnCompletionBehavior;
  onDisconnect?: DisconnectMode;
  feedbackKeys?: string[];
  streamMode?: Array<StreamMode>;
  runId?: string;
  optimisticValues?:
    | Partial<StateType>
    | ((prev: StateType) => Partial<StateType>);

  /**
   * Whether or not to stream the nodes of any subgraphs called
   * by the assistant.
   * @default false
   */
  streamSubgraphs?: boolean;

  /**
   * Mark the stream as resumable. All events emitted during the run will be temporarily persisted
   * in order to be re-emitted if the stream is re-joined.
   * @default false
   */
  streamResumable?: boolean;

  /**
   * Whether to checkpoint during the run (or only at the end/interruption).
   * - `"async"`: Save checkpoint asynchronously while the next step executes (default).
   * - `"sync"`: Save checkpoint synchronously before the next step starts.
   * - `"exit"`: Save checkpoint only when the graph exits.
   * @default "async"
   */
  durability?: Durability;

  /**
   * The ID to use when creating a new thread. When provided, this ID will be used
   * for thread creation when threadId is `null` or `undefined`.
   * This enables optimistic UI updates where you know the thread ID
   * before the thread is actually created.
   */
  threadId?: string;
}
