import React, { useRef } from "react";
import { ChevronRight, AlertTriangle, RefreshCw } from "lucide-react";
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
const ActivityPill: React.FC<WidgetProps> = ({ resultMessage, thread }) => {
  const { openActivity, close, isOpen } = useActivityPanel();
  const activity = parseActivity(resultMessage);
  // Защита от двойного клика по «Повторить» (submit асинхронный). Снимаем, когда
  // ран подхватился (isLoading) — иначе после ретрая тот же инстанс пилюли
  // остался бы с submittingRef=true и кнопка при следующей ошибке не нажималась.
  const submittingRef = useRef(false);
  React.useEffect(() => {
    if (thread?.isLoading) submittingRef.current = false;
  }, [thread?.isLoading]);

  // Показываем только завершённые раны; активный ран ведёт ThinkingIndicator.
  if (!activity || activity.finished_at == null) return null;

  // Ход упал ошибкой inner-рана: вместо «Работал N» рисуем ошибку с ретраем.
  // Ретрай переотправляет последний human с флагом experimental_retry — по нему
  // kickoff резюмит упавший inner-ран с чекпойнта (а не стартует ход заново).
  // Флаг едет в submit'е, поэтому переживает сброс кэша/рестарт (durable по R3).
  if (activity.error) {
    const handleRetry = () => {
      if (submittingRef.current || !thread) return;
      const messages = thread.messages ?? [];
      const lastHuman = [...messages].reverse().find((m) => m.type === "human");
      if (!lastHuman) return;
      submittingRef.current = true;
      // Тот же id → add_messages обновит human на месте, без второй копии.
      const id = lastHuman.id ?? crypto.randomUUID();
      const human = { ...lastHuman, id };
      void thread.submit(
        { messages: [human] },
        {
          streamMode: ["messages"],
          onDisconnect: "continue",
          config: {
            configurable: { experimental_retry: true, auto_approve: true },
          },
        },
      );
    };
    return (
      <div className="flex items-center gap-2 self-start rounded-lg border border-destructive bg-destructive/20 px-[10px] py-[8px] text-sm text-destructive-foreground">
        <AlertTriangle size={16} className="shrink-0" />
        Не удалось выполнить запрос
        <button
          type="button"
          aria-label="Повторить"
          onClick={handleRetry}
          disabled={!thread}
          className="shrink-0 cursor-pointer rounded-lg p-1.5 transition-colors hover:bg-destructive/40 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <RefreshCw size={15} />
        </button>
      </div>
    );
  }

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
