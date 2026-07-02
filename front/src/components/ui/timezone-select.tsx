import React, { useEffect, useRef, useState } from "react";
import { Check, ChevronsUpDown } from "lucide-react";

import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Command,
  CommandEmpty,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";

const FALLBACK_TIMEZONES = [
  "UTC",
  "Europe/Moscow",
  "Europe/Kaliningrad",
  "Europe/Samara",
  "Asia/Yekaterinburg",
  "Asia/Omsk",
  "Asia/Novosibirsk",
  "Asia/Krasnoyarsk",
  "Asia/Irkutsk",
  "Asia/Yakutsk",
  "Asia/Vladivostok",
  "Asia/Magadan",
  "Asia/Kamchatka",
  "Europe/London",
  "Europe/Berlin",
  "America/New_York",
  "America/Los_Angeles",
  "Asia/Tokyo",
];

/** Короткое UTC-смещение зоны на текущий момент, напр. "GMT+3". */
const tzOffsetLabel = (tz: string): string => {
  try {
    const part = new Intl.DateTimeFormat("en-US", {
      timeZone: tz,
      timeZoneName: "shortOffset",
    })
      .formatToParts(new Date())
      .find((p) => p.type === "timeZoneName");
    return part?.value ?? "";
  } catch {
    return "";
  }
};

const buildTimezoneOptions = (): { value: string; label: string }[] => {
  const supported = (
    Intl as unknown as { supportedValuesOf?: (key: string) => string[] }
  ).supportedValuesOf;
  let zones: string[];
  try {
    zones = supported ? supported("timeZone") : FALLBACK_TIMEZONES;
  } catch {
    zones = FALLBACK_TIMEZONES;
  }
  return zones.map((tz) => {
    const offset = tzOffsetLabel(tz);
    return { value: tz, label: offset ? `${tz} (${offset})` : tz };
  });
};

// Вычисляется один раз при загрузке модуля (смещения — на текущую дату).
const TIMEZONE_OPTIONS = buildTimezoneOptions();

interface TimezoneListProps {
  value?: string;
  onSelect: (value: string) => void;
}

/**
 * Внутренний список — монтируется вместе с контентом поповера, поэтому ref
 * гарантированно установлен. В Radix Dialog работает react-remove-scroll и
 * гасит wheel у порталов: вешаем non-passive listener и крутим scrollTop сами.
 * При открытии прокручиваем к текущему выбранному значению.
 */
const TimezoneList: React.FC<TimezoneListProps> = ({ value, onSelect }) => {
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap) return;
    const list = wrap.querySelector<HTMLElement>('[data-slot="command-list"]');

    const onWheel = (e: WheelEvent) => {
      if (!list) return;
      e.preventDefault();
      e.stopPropagation();
      list.scrollTop += e.deltaY;
    };
    wrap.addEventListener("wheel", onWheel, { passive: false });

    // Скролл к выбранной зоне после первой отрисовки (после автоскролла cmdk).
    const raf = requestAnimationFrame(() => {
      const active = wrap.querySelector<HTMLElement>(
        '[data-tz-selected="true"]',
      );
      if (list && active) {
        list.scrollTop =
          active.offsetTop - list.clientHeight / 2 + active.clientHeight / 2;
      }
    });

    return () => {
      wrap.removeEventListener("wheel", onWheel);
      cancelAnimationFrame(raf);
    };
  }, []);

  return (
    <div ref={wrapRef}>
      <Command>
        <CommandInput placeholder="Поиск зоны..." />
        <CommandList className="relative">
          <CommandEmpty>Зона не найдена</CommandEmpty>
          {TIMEZONE_OPTIONS.map((option) => {
            const isSelected = option.value === value;
            return (
              <CommandItem
                key={option.value}
                value={option.label}
                data-tz-selected={isSelected ? "true" : undefined}
                onSelect={() => onSelect(option.value)}
              >
                <Check
                  className={cn(
                    "mr-2 size-4",
                    isSelected ? "opacity-100" : "opacity-0",
                  )}
                />
                <span className="truncate">{option.label}</span>
              </CommandItem>
            );
          })}
        </CommandList>
      </Command>
    </div>
  );
};

export interface TimezoneSelectProps {
  value?: string;
  onValueChange: (value: string) => void;
  id?: string;
  placeholder?: string;
  className?: string;
}

const TimezoneSelect: React.FC<TimezoneSelectProps> = ({
  value,
  onValueChange,
  id,
  placeholder = "Выберите зону",
  className,
}) => {
  const [open, setOpen] = useState(false);
  const selected = TIMEZONE_OPTIONS.find((o) => o.value === value);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          id={id}
          type="button"
          variant="outline"
          role="combobox"
          aria-expanded={open}
          className={cn(
            "w-full justify-between font-normal",
            !selected && "text-muted-foreground",
            className,
          )}
        >
          <span className="truncate">{selected?.label ?? placeholder}</span>
          <ChevronsUpDown className="ml-2 size-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className="w-[var(--radix-popover-trigger-width)] p-0"
        style={{ zIndex: 9999 }}
      >
        {open && (
          <TimezoneList
            value={value}
            onSelect={(v) => {
              onValueChange(v);
              setOpen(false);
            }}
          />
        )}
      </PopoverContent>
    </Popover>
  );
};

export default TimezoneSelect;
