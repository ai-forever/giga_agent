import React, { useMemo } from "react";
import { CalendarDays } from "lucide-react";
import type { Message } from "@langchain/langgraph-sdk";
import type { ToolCall } from "@langchain/core/messages/tool";

import { WidgetShell, EmptyState } from "./kit";
import type { CalendarEvent, CalendarMonthPayload } from "./kit";

/**
 * GenUI-виджет «месяц-грид» календаря (маркер `widget:"calendar_month"`).
 * Сетка недель×дней (пн-первый), в ячейке номер дня + события. Время и день
 * берём из wall-clock ISO напрямую (без new Date — иначе tz браузера сдвигает
 * «плавающее» время). Read-only: создание/удаление — через агента.
 */

const WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
const MONTHS = [
  "Январь",
  "Февраль",
  "Март",
  "Апрель",
  "Май",
  "Июнь",
  "Июль",
  "Август",
  "Сентябрь",
  "Октябрь",
  "Ноябрь",
  "Декабрь",
];

function hhmm(iso?: string): string {
  if (!iso || !iso.includes("T")) return "";
  const m = iso.match(/T(\d{2}:\d{2})/);
  return m ? m[1] : "";
}

const MonthGrid: React.FC<{
  toolCall: ToolCall;
  resultMessage?: Message;
  isStreaming: boolean;
}> = ({ resultMessage, isStreaming }) => {
  const payload = useMemo<CalendarMonthPayload | null>(() => {
    if (!resultMessage) return null;
    try {
      const raw =
        typeof resultMessage.content === "string"
          ? JSON.parse(resultMessage.content)
          : resultMessage.content;
      const inner = (raw as any)?.data ?? raw;
      return inner?.widget === "calendar_month" ? inner : null;
    } catch {
      return null;
    }
  }, [resultMessage]);

  const grid = useMemo(() => {
    if (!payload) return null;
    const { year, month } = payload;
    const monthKey = `${year}-${String(month).padStart(2, "0")}`;
    // События по дню месяца (wall-clock из ISO).
    const byDay = new Map<number, CalendarEvent[]>();
    for (const ev of payload.events ?? []) {
      if (!ev.start || ev.start.slice(0, 7) !== monthKey) continue;
      const day = Number(ev.start.slice(8, 10));
      (byDay.get(day) ?? byDay.set(day, []).get(day)!).push(ev);
    }
    const daysInMonth = new Date(year, month, 0).getDate();
    const firstDow = (new Date(year, month - 1, 1).getDay() + 6) % 7; // пн=0
    const cells: (number | null)[] = [];
    for (let i = 0; i < firstDow; i++) cells.push(null);
    for (let d = 1; d <= daysInMonth; d++) cells.push(d);
    while (cells.length % 7 !== 0) cells.push(null);
    return { cells, byDay, total: (payload.events ?? []).length };
  }, [payload]);

  if (!resultMessage) {
    return (
      <WidgetShell>
        <EmptyState loading={isStreaming}>Открываю месяц…</EmptyState>
      </WidgetShell>
    );
  }
  if (!payload || !grid) {
    return (
      <WidgetShell>
        <EmptyState tone="error">Некорректный ответ календаря</EmptyState>
      </WidgetShell>
    );
  }

  const now = new Date();
  const isCurrentMonth =
    now.getFullYear() === payload.year && now.getMonth() + 1 === payload.month;
  const today = now.getDate();

  return (
    <WidgetShell>
      <div className="mb-1.5 flex items-center gap-1.5 px-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        <CalendarDays size={12} />
        {MONTHS[payload.month - 1]} {payload.year} · {grid.total}
      </div>
      <div className="grid grid-cols-7 gap-px overflow-hidden rounded-md bg-border/40">
        {WEEKDAYS.map((w) => (
          <div
            key={w}
            className="bg-muted/40 py-1 text-center text-[10px] font-medium text-muted-foreground"
          >
            {w}
          </div>
        ))}
        {grid.cells.map((day, i) => {
          if (day === null) {
            return <div key={`e${i}`} className="min-h-[58px] bg-card/30" />;
          }
          const evs = grid.byDay.get(day) ?? [];
          const isToday = isCurrentMonth && day === today;
          return (
            <div key={day} className="min-h-[58px] bg-card/60 p-1 align-top">
              <div
                className={`mb-0.5 inline-flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-[10px] ${
                  isToday
                    ? "bg-blue-500 font-semibold text-white"
                    : "text-muted-foreground"
                }`}
              >
                {day}
              </div>
              <div className="flex flex-col gap-0.5">
                {evs.slice(0, 2).map((ev) => (
                  <div
                    key={ev.uid || `${ev.summary}-${ev.start}`}
                    title={`${hhmm(ev.start)} ${ev.summary}`.trim()}
                    className="truncate rounded-sm border-l-2 border-blue-500/50 bg-blue-500/10 px-1 text-[10px] leading-tight"
                  >
                    {hhmm(ev.start) && (
                      <span className="text-muted-foreground">
                        {hhmm(ev.start)}{" "}
                      </span>
                    )}
                    {ev.summary}
                  </div>
                ))}
                {evs.length > 2 && (
                  <div className="px-1 text-[10px] text-muted-foreground">
                    +{evs.length - 2}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </WidgetShell>
  );
};

export default MonthGrid;
