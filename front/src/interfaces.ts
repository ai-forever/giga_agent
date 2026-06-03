import { Message } from "@langchain/langgraph-sdk";
import { Collection } from "@/types/collection.ts";

import type { Tool } from "@modelcontextprotocol/sdk/types.d.ts";
import type { ToolCall } from "@langchain/core/messages/tool";

export type Secret = {
  name: string;
  value: string;
  description?: string;
};

export interface GraphState extends Record<string, unknown> {
  messages: Message[];
  collections: Collection[];
  mcp_tools: Tool[];
  instructions: string;
  secrets: Secret[];
  disabled_modules: string[];
}

type BagTemplate = {
  ConfigurableType?: Record<string, unknown>;
  InterruptType?: unknown;
  CustomEventType?: unknown;
  UpdateType?: unknown;
};

export interface GraphInterrupt {
  type: "approve" | "comment" | "tool_call" | "confirm_destructive";
  tools?: ToolCall[];
}

export interface GraphTemplate extends BagTemplate {
  InterruptType: GraphInterrupt;
}

export interface FileData {
  path: string;
  original_name?: string;
  file_type?: string;
  size: number;
  image_id?: string;
  image_path?: string;
}

export interface MessageData {
  message: string;
  attachments: FileData[];
}

export interface DemoItem {
  id: string;
  json_data: Partial<MessageData>;
  steps: number;
  sorting: number;
  active: boolean;
}
