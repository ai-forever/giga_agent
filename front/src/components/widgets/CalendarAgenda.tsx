import React, { useMemo } from "react";
import { MapPin, CalendarDays } from "lucide-react";
import type { Message } from "@langchain/langgraph-sdk";
import type { ToolCall } from "@langchain/core/messages/tool";

import { WidgetShell, EmptyState } from "./kit";
import type { CalendarEvent, CalendarAgendaPayload } from "./kit";

/**
 * GenUI-виджет «агенда» календаря, маршрутизируемый по маркеру
 * `widget:"calendar_agenda"` (provider-agnostic, как трекер/диск/почта).
 * События сгруппированы по дням; время/название/место. Удаление — через
 * агента (деструктив под confirm), не из виджета.
 */

const isAllDay = (start?: string): boolean => !!start && !start.includes("T");

function dayKey(start?: string): string {
  if (!start) return "";
  return start.slice(0, 10); // YYYY-MM-DD
}

function dayLabel(key: string): string {
  const d = new Date(`${key}T00:00:00`);
  if (Number.isNaN(d.getTime())) return key;
  return d.toLocaleDateString("ru-RU", {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
}

function hhmm(iso?: string): string {
  // Берём wall-clock HH:MM прямо из строки, БЕЗ new Date() — иначе tz браузера
  // сдвигает время (события пишутся «плавающим» временем). Так показываем ровно
  // то, что в календаре, совпадая с текстом модели.
  if (!iso || !iso.includes("T")) return "";
  const m = iso.match(/T(\d{2}:\d{2})/);
  return m ? m[1] : "";
}

function timeRange(ev: CalendarEvent): string {
  if (isAllDay(ev.start)) return "весь день";
  const s = hhmm(ev.start);
  const e = hhmm(ev.end);
  return e ? `${s}–${e}` : s;
}

const CalendarAgenda: React.FC<{
  toolCall: ToolCall;
  resultMessage?: Message;
  isStreaming: boolean;
}> = ({ resultMessage, isStreaming }) => {
  const payload = useMemo<CalendarAgendaPayload | null>(() => {
    if (!resultMessage) return null;
    try {
      const raw =
        typeof resultMessage.content === "string"
          ? JSON.parse(resultMessage.content)
          : resultMessage.content;
      const inner = (raw as any)?.data ?? raw;
      return inner?.widget === "calendar_agenda" ? inner : null;
    } catch {
      return null;
    }
  }, [resultMessage]);

  const groups = useMemo(() => {
    const events = payload?.events ?? [];
    const map = new Map<string, CalendarEvent[]>();
    for (const ev of events) {
      const k = dayKey(ev.start) || "—";
      (map.get(k) ?? map.set(k, []).get(k)!).push(ev);
    }
    return [...map.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [payload]);

  if (!resultMessage) {
    return (
      <WidgetShell>
        <EmptyState loading={isStreaming}>Смотрю календарь…</EmptyState>
      </WidgetShell>
    );
  }
  if (!payload) {
    return (
      <WidgetShell>
        <EmptyState tone="error">Некорректный ответ календаря</EmptyState>
      </WidgetShell>
    );
  }

  const total = payload.events?.length ?? 0;
  if (!total) {
    return (
      <WidgetShell>
        <div className="mb-1 px-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          Повестка · {payload.days} дн
        </div>
        <EmptyState>Событий нет</EmptyState>
      </WidgetShell>
    );
  }

  return (
    <WidgetShell>
      <div className="mb-1.5 flex items-center gap-1.5 px-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        <CalendarDays size={12} />
        Повестка · {total}
      </div>
      <div className="flex flex-col gap-2.5">
        {groups.map(([key, evs]) => (
          <div key={key}>
            <div className="mb-1 px-1 text-[11px] font-medium capitalize text-muted-foreground/80">
              {dayLabel(key)}
            </div>
            <div className="flex flex-col gap-1">
              {evs.map((ev) => (
                <div
                  key={ev.uid || `${ev.summary}-${ev.start}`}
                  className="flex items-baseline gap-2 rounded-md border-l-2 border-blue-500/40 bg-card/60 px-2 py-1.5 text-sm"
                >
                  <span className="shrink-0 whitespace-nowrap font-mono text-[11px] tabular-nums text-muted-foreground">
                    {timeRange(ev)}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-medium leading-snug">
                      {ev.summary || "(без названия)"}
                    </div>
                    {ev.location && (
                      <div className="mt-0.5 flex items-center gap-1 truncate text-[11px] text-muted-foreground">
                        <MapPin size={10} />
                        {ev.location}
                      </div>
                    )}
                  </div>
                  {ev.calendar && (
                    <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                      {ev.calendar}
                    </span>
                  )}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </WidgetShell>
  );
};

export default CalendarAgenda;
