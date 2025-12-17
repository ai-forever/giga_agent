import { Message } from "@langchain/langgraph-sdk";
import { Collection } from "@/types/collection.ts";

import { Tool } from "mcp-use/react";

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
}

type BagTemplate = {
  ConfigurableType?: Record<string, unknown>;
  InterruptType?: unknown;
  CustomEventType?: unknown;
  UpdateType?: unknown;
};

export interface GraphInterrupt {
  type: "approve" | "comment" | "tool_call";
  tool_name?: string;
  args?: any;
}

export interface GraphTemplate extends BagTemplate {
  InterruptType: GraphInterrupt;
}

export interface FileData {
  path: string;
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
