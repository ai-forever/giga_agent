import type { Message } from "@langchain/langgraph-sdk";
import type {
  AnsweredQuestion,
  GraphState,
  Question,
  QuestionAnswer,
  QuestionsResult,
} from "../../interfaces.ts";

export const ASK_QUESTIONS_TOOL_NAME = "ask_questions";

// Детерминированные id заглушки-носителя и ToolMessage. ДОЛЖНЫ совпадать с
// бэкендом (experimental/graph.py: _stub_message_id / _ask_questions_messages) —
// тогда серверный коммит склеивается с оптимистикой по id, а не создаёт вторую
// заглушку/карточку.
export const stubMessageId = (toolCallId: string) => `exp-toolstub-${toolCallId}`;
export const toolMessageId = (toolCallId: string) => `exp-toolmsg-${toolCallId}`;

// Собрать структуру ответа ровно так, как это делает backend-тул ask_questions
// (items с ТЕКСТАМИ выбранных опций + "Q: …\nA: …"-summary) — чтобы карточка
// «как ответил пользователь» отрисовалась оптимистично, до серверного
// ToolMessage. Формат читается getQuestionsResult (см. questions/detect.ts).
export const buildAnsweredResult = (
  questions: Question[],
  answers: QuestionAnswer[],
): QuestionsResult => {
  const answerByQuestion = new Map(answers.map((a) => [a.question_id, a]));
  const items: AnsweredQuestion[] = [];
  const parts: string[] = [];
  for (const q of questions) {
    const answer = answerByQuestion.get(q.id);
    const optionText = new Map(q.options.map((o) => [o.id, o.text]));
    const selected = (answer?.selected ?? []).map(
      (id) => optionText.get(id) ?? id,
    );
    const otherText = answer?.other_text ?? "";
    items.push({
      question: q.text,
      type: q.type,
      options: q.options.map((o) => o.text),
      selected,
      other_text: otherText,
    });
    const all = [...selected, ...(otherText ? [otherText] : [])];
    if (all.length) parts.push(`Q: ${q.text}\nA: ${all.join(", ")}`);
  }
  return {
    skipped: false,
    summary: parts.join("\n\n") || "Пользователь не предоставил ответ.",
    items,
  };
};

// Пропуск вопросов (ветка `comment` backend-тула): пустой message = чистый
// пропуск, непустой = свободный ответ мимо вариантов.
export const buildCommentResult = (message: string): QuestionsResult => ({
  skipped: true,
  comment: message,
  summary: message
    ? `Пользователь пропустил вопросы и ответил: "${message}"`
    : "Пользователь пропустил вопросы и не оставил ответа.",
  items: [],
});

// tool_call_id прерывающего ask_questions среди уже пришедших сообщений (обычный
// чат — AI-сообщение с этим tool_call уже есть). В обёртке его нет — тогда id
// берут из interrupt value.
export const findCarrierToolCallId = (
  messages: Message[],
): string | undefined => {
  for (let i = messages.length - 1; i >= 0; i--) {
    const toolCalls = ((messages[i] as any).tool_calls ?? []) as Array<{
      id?: string;
      name?: string;
    }>;
    const tc = toolCalls.find((c) => c?.name === ASK_QUESTIONS_TOOL_NAME);
    if (tc?.id) return tc.id;
  }
  return undefined;
};

// optimisticValues-функция: дописать результат ask_questions. Всегда добавляем
// ToolMessage; если готового AI-носителя нет (обёртка) — ещё и AI-заглушку с
// tool_call, к которой привяжется карточка. id детерминированы и совпадают с
// серверным коммитом (interrupt_node) → без дубля и морганий.
export const appendAskQuestionsResult =
  (
    toolCallId: string | undefined,
    carrierExists: boolean,
    result: QuestionsResult,
  ) =>
  (prev: GraphState): Partial<GraphState> => {
    if (!toolCallId) return {};
    const extra: Message[] = [];
    if (!carrierExists) {
      extra.push({
        type: "ai",
        id: stubMessageId(toolCallId),
        content: "",
        // rendered: true — как у серверной заглушки; без него Message.tsx падает
        // на message.additional_kwargs["rendered"].
        additional_kwargs: { rendered: true },
        tool_calls: [
          {
            id: toolCallId,
            name: ASK_QUESTIONS_TOOL_NAME,
            args: {},
            type: "tool_call",
          },
        ],
      } as unknown as Message);
    }
    extra.push({
      type: "tool",
      id: toolMessageId(toolCallId),
      tool_call_id: toolCallId,
      name: ASK_QUESTIONS_TOOL_NAME,
      status: "success",
      content: JSON.stringify({ ask_questions: true, ...result }),
      additional_kwargs: { tool_name: ASK_QUESTIONS_TOOL_NAME },
    } as unknown as Message);
    return { ...prev, messages: [...(prev.messages ?? []), ...extra] };
  };
