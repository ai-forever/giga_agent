import React, { useEffect, useRef } from "react";

import { cn } from "@/lib/utils";

const pad = (n: number) => String(n).padStart(2, "0");

export interface ScrollColumnProps {
  values: number[];
  selected: number;
  onSelect: (v: number) => void;
  className?: string;
}

/**
 * Вертикальная скролл-колонка чисел с подсветкой выбранного значения.
 * Активное значение центрируется (mount — мгновенно, смена — плавно).
 * Внутри Radix Dialog/Popover react-remove-scroll гасит wheel у порталов —
 * вешаем non-passive listener и крутим scrollTop вручную.
 */
export const ScrollColumn: React.FC<ScrollColumnProps> = ({
  values,
  selected,
  onSelect,
  className,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const activeRef = useRef<HTMLButtonElement>(null);
  const firstRun = useRef(true);

  useEffect(() => {
    const c = containerRef.current;
    const a = activeRef.current;
    if (c && a) {
      const top = a.offsetTop - c.clientHeight / 2 + a.clientHeight / 2;
      c.scrollTo({ top, behavior: firstRun.current ? "auto" : "smooth" });
    }
    firstRun.current = false;
  }, [selected]);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      e.stopPropagation();
      el.scrollTop += e.deltaY;
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  return (
    <div
      ref={containerRef}
      className={cn(
        "relative flex h-[208px] flex-col gap-0.5 overflow-y-auto px-1 [scrollbar-width:thin]",
        className,
      )}
    >
      {values.map((v) => {
        const isActive = v === selected;
        return (
          <button
            key={v}
            type="button"
            ref={isActive ? activeRef : undefined}
            onClick={() => onSelect(v)}
            className={cn(
              "shrink-0 rounded-md px-3 py-1.5 text-sm tabular-nums transition-colors",
              isActive
                ? "bg-primary text-primary-foreground"
                : "text-foreground hover:bg-accent hover:text-accent-foreground",
            )}
          >
            {pad(v)}
          </button>
        );
      })}
    </div>
  );
};

export interface TimeColumnsProps {
  hour: number;
  minute: number;
  onChange: (hour: number, minute: number) => void;
  className?: string;
  columnClassName?: string;
}

/** Колонки «часы : минуты». */
export const TimeColumns: React.FC<TimeColumnsProps> = ({
  hour,
  minute,
  onChange,
  className,
  columnClassName,
}) => (
  <div className={cn("flex gap-1", className)}>
    <ScrollColumn
      values={Array.from({ length: 24 }, (_, i) => i)}
      selected={hour}
      onSelect={(h) => onChange(h, minute)}
      className={columnClassName}
    />
    <div className="flex items-center text-muted-foreground">:</div>
    <ScrollColumn
      values={Array.from({ length: 60 }, (_, i) => i)}
      selected={minute}
      onSelect={(m) => onChange(hour, m)}
      className={columnClassName}
    />
  </div>
);
