import React, { useEffect, useMemo, useState } from "react";
import {
  addMonths,
  eachDayOfInterval,
  endOfWeek,
  format,
  isSameDay,
  isSameMonth,
  isToday,
  setHours,
  setMinutes,
  startOfMonth,
  startOfWeek,
  subMonths,
} from "date-fns";
import { ru } from "date-fns/locale";
import { CalendarDays, ChevronLeft, ChevronRight, Clock } from "lucide-react";

import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { ScrollColumn } from "@/components/ui/time-columns";

const WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];

/** datetime-local-строка (`YYYY-MM-DDTHH:mm`) → Date | null */
const parseLocal = (value: string): Date | null => {
  if (!value) return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
};

const pad = (n: number) => String(n).padStart(2, "0");

/** Date → datetime-local-строка (`YYYY-MM-DDTHH:mm`) */
const toLocal = (d: Date): string =>
  `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(
    d.getHours(),
  )}:${pad(d.getMinutes())}`;

export interface DateTimePickerProps {
  /** datetime-local-строка `YYYY-MM-DDTHH:mm` */
  value: string;
  onChange: (value: string) => void;
  id?: string;
  placeholder?: string;
  className?: string;
}

const DateTimePicker: React.FC<DateTimePickerProps> = ({
  value,
  onChange,
  id,
  placeholder = "Выберите дату и время",
  className,
}) => {
  const [open, setOpen] = useState(false);
  const selected = useMemo(() => parseLocal(value), [value]);
  // Месяц, отображаемый в сетке: выбранный либо текущий
  const [viewMonth, setViewMonth] = useState<Date>(() =>
    startOfMonth(selected ?? new Date()),
  );

  // При открытии возвращаем сетку к выбранной дате
  useEffect(() => {
    if (open) setViewMonth(startOfMonth(selected ?? new Date()));
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const days = useMemo(() => {
    const start = startOfWeek(startOfMonth(viewMonth), { weekStartsOn: 1 });
    const end = endOfWeek(startOfMonth(addMonths(viewMonth, 1)), {
      weekStartsOn: 1,
    });
    // endOfWeek от начала следующего месяца захватывает лишнюю неделю — обрежем
    return eachDayOfInterval({ start, end }).slice(0, 42);
  }, [viewMonth]);

  const hours = selected?.getHours() ?? 9;
  const minutes = selected?.getMinutes() ?? 0;

  const commit = (next: Date) => onChange(toLocal(next));

  const pickDay = (day: Date) => {
    const base = selected ?? setMinutes(setHours(new Date(), 9), 0);
    const next = setMinutes(setHours(day, base.getHours()), base.getMinutes());
    commit(next);
  };

  const pickHour = (h: number) => {
    const base = selected ?? startOfMonth(new Date());
    commit(setHours(base, h));
  };

  const pickMinute = (m: number) => {
    const base = selected ?? startOfMonth(new Date());
    commit(setMinutes(base, m));
  };

  const label = selected
    ? format(selected, "d MMMM yyyy, HH:mm", { locale: ru })
    : placeholder;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          id={id}
          type="button"
          variant="outline"
          className={cn(
            "w-full justify-start font-normal",
            !selected && "text-muted-foreground",
            className,
          )}
        >
          <CalendarDays className="mr-2 size-4 shrink-0 opacity-70" />
          <span className="truncate">{label}</span>
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className="z-[9999] w-auto p-0"
        sideOffset={6}
      >
        <div className="flex divide-x divide-border">
          {/* Календарь */}
          <div className="p-3">
            <div className="mb-2 flex items-center justify-between">
              <button
                type="button"
                onClick={() => setViewMonth((m) => subMonths(m, 1))}
                className="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
              >
                <ChevronLeft className="size-4" />
              </button>
              <div className="text-sm font-medium capitalize">
                {format(viewMonth, "LLLL yyyy", { locale: ru })}
              </div>
              <button
                type="button"
                onClick={() => setViewMonth((m) => addMonths(m, 1))}
                className="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
              >
                <ChevronRight className="size-4" />
              </button>
            </div>

            <div className="grid grid-cols-7 gap-0.5">
              {WEEKDAYS.map((w) => (
                <div
                  key={w}
                  className="flex h-8 items-center justify-center text-xs font-medium text-muted-foreground"
                >
                  {w}
                </div>
              ))}
              {days.map((day) => {
                const inMonth = isSameMonth(day, viewMonth);
                const isSelected = selected && isSameDay(day, selected);
                const today = isToday(day);
                return (
                  <button
                    key={day.toISOString()}
                    type="button"
                    onClick={() => pickDay(day)}
                    className={cn(
                      "flex size-8 items-center justify-center rounded-md text-sm tabular-nums transition-colors",
                      !inMonth && "text-muted-foreground/40",
                      inMonth && "text-foreground",
                      isSelected && "bg-primary text-primary-foreground",
                      !isSelected &&
                        "hover:bg-accent hover:text-accent-foreground",
                      today &&
                        !isSelected &&
                        "ring-1 ring-inset ring-border font-medium",
                    )}
                  >
                    {day.getDate()}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Время */}
          <div className="flex flex-col p-3">
            <div className="mb-2 flex items-center justify-center gap-1.5 text-sm font-medium text-muted-foreground">
              <Clock className="size-4" />
              Время
            </div>
            <div className="flex gap-1">
              <ScrollColumn
                values={Array.from({ length: 24 }, (_, i) => i)}
                selected={hours}
                onSelect={pickHour}
              />
              <div className="flex items-center text-muted-foreground">:</div>
              <ScrollColumn
                values={Array.from({ length: 60 }, (_, i) => i)}
                selected={minutes}
                onSelect={pickMinute}
              />
            </div>
          </div>
        </div>

        <div className="flex items-center justify-between gap-2 border-t border-border p-2">
          <button
            type="button"
            onClick={() => {
              const now = new Date();
              commit(setMinutes(now, now.getMinutes()));
              setViewMonth(startOfMonth(now));
            }}
            className="rounded-md px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
          >
            Сейчас
          </button>
          <Button size="sm" onClick={() => setOpen(false)}>
            Готово
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
};

export default DateTimePicker;
