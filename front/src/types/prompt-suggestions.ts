export interface PromptSuggestionScenario {
  title?: string;
  text: string;
  deepResearchForced?: boolean;
  skills?: string[];
  ragMode?: "all" | "off";
  modules?: Record<string, boolean>;
}

const MAX_TITLE_LEN = 84;

const toSingleLine = (text: string): string => text.replace(/\s+/g, " ").trim();

export function getPromptSuggestionTitle(
  suggestion: Pick<PromptSuggestionScenario, "title" | "text">,
): string {
  const preferred = toSingleLine(suggestion.title ?? "");
  if (preferred) return preferred;

  const normalizedText = toSingleLine(suggestion.text);
  if (normalizedText.length <= MAX_TITLE_LEN) return normalizedText;
  return `${normalizedText.slice(0, MAX_TITLE_LEN - 1).trimEnd()}…`;
}

export function normalizePromptSuggestion(
  value: unknown,
): PromptSuggestionScenario | null {
  if (typeof value === "string") {
    const text = value.trim();
    if (!text) return null;
    return { text, title: getPromptSuggestionTitle({ text }) };
  }
  if (!value || typeof value !== "object") {
    return null;
  }

  const record = value as Record<string, unknown>;
  const textValue = record.text;
  if (typeof textValue !== "string") {
    return null;
  }

  const text = textValue.trim();
  if (!text) {
    return null;
  }

  const deepResearchForced =
    typeof record.deepResearchForced === "boolean"
      ? record.deepResearchForced
      : undefined;

  const skills = Array.isArray(record.skills)
    ? record.skills.filter((item): item is string => typeof item === "string")
    : undefined;

  const ragMode =
    record.ragMode === "all" || record.ragMode === "off"
      ? record.ragMode
      : undefined;

  const modules =
    record.modules && typeof record.modules === "object"
      ? Object.fromEntries(
          Object.entries(record.modules as Record<string, unknown>).filter(
            (entry): entry is [string, boolean] => typeof entry[1] === "boolean",
          ),
        )
      : undefined;

  const title =
    typeof record.title === "string" && record.title.trim()
      ? toSingleLine(record.title)
      : undefined;

  return {
    ...(title ? { title } : {}),
    text,
    ...(deepResearchForced !== undefined ? { deepResearchForced } : {}),
    ...(skills && skills.length > 0 ? { skills } : {}),
    ...(ragMode ? { ragMode } : {}),
    ...(modules && Object.keys(modules).length > 0 ? { modules } : {}),
  };
}
