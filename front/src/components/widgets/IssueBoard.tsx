import React, { useMemo } from "react";
import type { Message } from "@langchain/langgraph-sdk";
import type { ToolCall } from "@langchain/core/messages/tool";

import { Board } from "./kit";
import type { Issue } from "./kit";

/**
 * Адаптер Яндекс.Трекера: маппит бытовую форму его тулов
 * (tracker_search_issues / tracker_get_issue) в нормализованный контракт Issue
 * и рендерит кит-Board. Когда Яндекс перейдёт на нормализованный бэкенд-контракт
 * (шаг 2: BaseTrackerModule), этот адаптер удаляется — останется BoardWidget.
 */

const PROVIDER = "yandex_tracker";

interface YandexIssue {
  key: string;
  summary?: string;
  status?: string;
  assignee?: string;
  queue?: string;
  priority?: string;
  updatedAt?: string;
  description?: string;
}

// Короткая дата «8 июн» / «8 июн 2025».
function shortDate(iso?: string): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  const now = new Date();
  const opts: Intl.DateTimeFormatOptions =
    d.getFullYear() === now.getFullYear()
      ? { day: "numeric", month: "short" }
      : { day: "numeric", month: "short", year: "numeric" };
  return d.toLocaleDateString("ru-RU", opts);
}

function toIssue(y: YandexIssue): Issue {
  const fields = [];
  if (y.assignee)
    fields.push({ icon: "user", label: "Исполнитель", value: y.assignee });
  if (y.priority)
    fields.push({ icon: "flag", label: "Приоритет", value: y.priority });
  const date = shortDate(y.updatedAt);
  if (date) fields.push({ icon: "clock", label: "Обновлено", value: date });
  return {
    id: y.key,
    key: y.key,
    title: y.summary || "",
    status: y.status,
    provider: PROVIDER,
    description: y.description,
    tag: y.queue,
    fields,
  };
}

const IssueBoard: React.FC<{
  toolCall: ToolCall;
  resultMessage?: Message;
  isStreaming: boolean;
}> = ({ resultMessage, isStreaming }) => {
  const parsed = useMemo<{ issues: Issue[]; error?: string }>(() => {
    if (!resultMessage) return { issues: [] };
    let payload: any;
    try {
      payload =
        typeof resultMessage.content === "string"
          ? JSON.parse(resultMessage.content)
          : resultMessage.content;
    } catch {
      return { issues: [] };
    }
    const inner = payload?.data ?? payload;
    if (inner?.error) return { issues: [], error: String(inner.error) };
    if (Array.isArray(inner?.issues))
      return { issues: (inner.issues as YandexIssue[]).map(toIssue) };
    if (inner?.key) return { issues: [toIssue(inner as YandexIssue)] };
    return { issues: [] };
  }, [resultMessage]);

  return (
    <Board
      issues={parsed.issues}
      error={parsed.error}
      loading={!resultMessage && isStreaming}
    />
  );
};

export default IssueBoard;
