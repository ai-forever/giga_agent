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
  ui?: any[];
}

export interface PlanTodo {
  id: string;
  title: string;
  status?: "pending" | "in_progress" | "completed" | "skipped";
  note?: string;
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
    | "confirm_destructive"
    | "plan_approval";
  tools?: ToolCall[];
  plan?: PlanTodo[];
  questions?: Question[];
  // tool_call_id вопросов ask_questions. Проставляет обёртка
  // giga_agent_experimental (во внешнем графе AI-сообщения с этим tool_call на
  // момент interrupt'а ещё нет), чтобы оптимистичная карточка привязалась к нему.
  tool_call_id?: string;
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

// Лог активности хода в экспериментальном режиме: вызванные инструменты и
// показанные строки-статусы, упорядоченные по времени (`ts`, epoch-секунды).
// Встраивается в маркер-ToolMessage `experimental_activity` и отдаётся живой
// ручкой /agent/experimental/activity/{thread_id}.
export interface ActivityStatusItem {
  type: "status";
  text: string;
  ts: number;
}

export interface ActivityToolItem {
  type: "tool";
  id: string;
  name: string;
  status: "running" | "success" | "error";
  ts: number;
  ts_end: number | null;
}

export type ActivityItem = ActivityStatusItem | ActivityToolItem;

export interface Activity {
  started_at: number | null;
  finished_at: number | null;
  items: ActivityItem[];
  // Ход завершился ошибкой inner-рана: пилюля рисует ошибку + кнопку «Повторить»
  // (бэк проставляет во встроенном снапшоте маркера, см. graph.pump).
  error?: boolean;
}
