import React from "react";
import { ChevronRight } from "lucide-react";
import type { Message } from "@langchain/langgraph-sdk";
import type { WidgetProps } from "./registry";
import type { Activity } from "@/interfaces";
import { useActivityPanel } from "../experimental/ActivityPanelProvider";
import { formatDuration } from "../experimental/format";

// Достаёт встроенный снапшот активности из payload маркера. content лежит плоско:
// {"widget":"experimental_activity","started_at":..,"finished_at":..,"items":[..]}
// (маркер `widget` — там, где его ищет payloadWidgetKind; лишнее поле игнорим).
function parseActivity(resultMessage?: Message): Activity | null {
  if (!resultMessage) return null;
  try {
    const raw =
      typeof resultMessage.content === "string"
        ? JSON.parse(resultMessage.content)
        : resultMessage.content;
    return raw && typeof raw === "object" ? (raw as Activity) : null;
  } catch {
    return null;
  }
}

/**
 * Надпись «Работал N» — маркер активности ЗАВЕРШЁННОГО хода. Пока ход активен,
 * маркер скрыт: живой прогресс показывает ThinkingIndicator (клик по нему
 * открывает панель). Клик по надписи открывает панель из встроенного снапшота.
 */
const ActivityPill: React.FC<WidgetProps> = ({ resultMessage }) => {
  const { openActivity, close, isOpen } = useActivityPanel();
  const activity = parseActivity(resultMessage);

  // Показываем только завершённые раны; активный ран ведёт ThinkingIndicator.
  if (!activity || activity.finished_at == null) return null;

  const duration =
    activity.started_at != null
      ? ` ${formatDuration(activity.finished_at - activity.started_at)}`
      : "";

  return (
    <button
      type="button"
      onClick={() => (isOpen ? close() : openActivity(activity))}
      className="inline-flex items-center gap-1 self-start text-sm text-muted-foreground transition-colors hover:text-foreground cursor-pointer"
    >
      <ChevronRight size={15} className="flex-shrink-0" />
      {`Работал${duration}`}
    </button>
  );
};

export default ActivityPill;
