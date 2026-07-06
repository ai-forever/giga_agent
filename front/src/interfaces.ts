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
  disabled_modules: string[];
}

type BagTemplate = {
  ConfigurableType?: Record<string, unknown>;
  InterruptType?: unknown;
  CustomEventType?: unknown;
  UpdateType?: unknown;
};

export interface QuestionOption {
  id: string;
  text: string;
}

export interface Question {
  id: string;
  text: string;
  type: "single" | "multi";
  options: QuestionOption[];
}

export interface QuestionAnswer {
  question_id: string;
  selected: string[];
  other_text: string;
}

// Структурированный результат уже выполненного тула `ask_questions`:
// какие вопросы были заданы и как на них ответил пользователь.
export interface AnsweredQuestion {
  question: string;
  type: "single" | "multi";
  options: string[];
  selected: string[];
  other_text: string;
}

export interface QuestionsResult {
  skipped: boolean;
  comment?: string;
  summary: string;
  items: AnsweredQuestion[];
}

export interface GraphInterrupt {
  type:
    | "approve"
    | "comment"
    | "tool_call"
    | "questions"
    | "confirm_destructive";
  tools?: ToolCall[];
  questions?: Question[];
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
