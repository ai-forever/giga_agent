import type { Message } from "@langchain/langgraph-sdk";
import type { AnsweredQuestion, QuestionsResult } from "../../interfaces";

const toItems = (raw: any): AnsweredQuestion[] =>
  Array.isArray(raw)
    ? raw.map((it: any) => ({
        question: String(it?.question ?? ""),
        type: it?.type === "multi" ? "multi" : "single",
        options: Array.isArray(it?.options) ? it.options.map(String) : [],
        selected: Array.isArray(it?.selected) ? it.selected.map(String) : [],
        other_text: String(it?.other_text ?? ""),
      }))
    : [];

// Legacy `ask_questions` results stored only the "Q: …\nA: …" summary string.
// Reconstruct the card from the original questions (kept in tool_args) by
// matching each answer line back to the question's options.
const fromLegacy = (
  summary: string,
  toolArgs: any,
): QuestionsResult | null => {
  const text = summary.trim();
  if (text.startsWith("Пользователь пропустил")) {
    const m = text.match(/ответил:\s*"([\s\S]*)"\s*$/);
    return { skipped: true, comment: m?.[1], summary: text, items: [] };
  }

  const questions = toolArgs?.questions;
  if (!Array.isArray(questions) || questions.length === 0) return null;

  // Map each "Q: <text>\nA: <answer>" block to its answer text.
  const answerByQuestion = new Map<string, string>();
  for (const block of text.split(/\n\s*\n/)) {
    const m = block.match(/^Q:\s*([\s\S]*?)\s*\nA:\s*([\s\S]*)$/);
    if (m) answerByQuestion.set(m[1].trim(), m[2].trim());
  }

  const items: AnsweredQuestion[] = questions.map((q: any) => {
    const question = String(q?.text ?? "");
    const options = Array.isArray(q?.options) ? q.options.map(String) : [];
    const answer = answerByQuestion.get(question) ?? "";
    const selected = options.filter((opt: string) => opt && answer.includes(opt));
    // Couldn't map the answer onto any option → treat as free-text ("Other").
    const otherText = selected.length === 0 ? answer : "";
    return {
      question,
      type: q?.type === "multi" ? "multi" : "single",
      options,
      selected,
      other_text: otherText,
    };
  });

  return { skipped: false, summary: text, items };
};

/**
 * If a tool result is a completed `ask_questions` call, return the structured
 * questions + how the user answered them; otherwise null. Used to promote the
 * result out of the tool-call list and render it as a standalone read-only
 * "questions answered" card in the message flow (mirrors getScheduledTaskId).
 *
 * Supports both the structured result and the legacy plain-text summary
 * (reconstructed from tool_args), so historical threads still render.
 */
export const getQuestionsResult = (
  resultMessage?: Message,
): QuestionsResult | null => {
  if (!resultMessage) return null;
  const ak = (resultMessage as any).additional_kwargs || {};
  if (ak.tool_name !== "ask_questions") return null;
  if ((resultMessage as any).status === "error") return null;

  let content: unknown = (resultMessage as any).content;
  if (Array.isArray(content)) {
    content = content
      .map((p) => (typeof p === "string" ? p : (p as any)?.text ?? ""))
      .join("");
  }
  if (typeof content !== "string" || !content.trim()) return null;

  let parsed: any;
  try {
    parsed = JSON.parse(content);
  } catch {
    // Raw (non-JSON) text — treat as a legacy summary.
    return fromLegacy(content, ak.tool_args);
  }

  // Structured format.
  if (parsed && typeof parsed === "object" && parsed.ask_questions === true) {
    return {
      skipped: Boolean(parsed.skipped),
      comment: typeof parsed.comment === "string" ? parsed.comment : undefined,
      summary: typeof parsed.summary === "string" ? parsed.summary : "",
      items: toItems(parsed.items),
    };
  }

  // Legacy format: content was a JSON-encoded summary string.
  if (typeof parsed === "string") {
    return fromLegacy(parsed, ak.tool_args);
  }

  return null;
};
