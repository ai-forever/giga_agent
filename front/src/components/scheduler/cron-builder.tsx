import React, { useEffect, useRef, useState } from "react";
import { Wand2, Code2 } from "lucide-react";
import cronstrue from "cronstrue/i18n";

import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

type Frequency =
  | "daily"
  | "weekly"
  | "monthly"
  | "hourly"
  | "everyMinutes"
  | "everyHours";

interface BuilderState {
  freq: Frequency;
  hour: number;
  minute: number;
  days: number[]; // 0=Вс ... 6=Сб
  dom: number; // число месяца 1–31
  nMinutes: number;
  nHours: number;
}

const FREQ_LABELS: Record<Frequency, string> = {
  daily: "Каждый день",
  weekly: "Каждую неделю",
  monthly: "Каждый месяц",
  hourly: "Каждый час",
  everyMinutes: "Каждые N минут",
  everyHours: "Каждые N часов",
};

// Порядок и значения дней (Пн первым, как в русском календаре)
const WEEKDAYS: { value: number; short: string }[] = [
  { value: 1, short: "Пн" },
  { value: 2, short: "Вт" },
  { value: 3, short: "Ср" },
  { value: 4, short: "Чт" },
  { value: 5, short: "Пт" },
  { value: 6, short: "Сб" },
  { value: 0, short: "Вс" },
];
const pad = (n: number) => String(n).padStart(2, "0");
const isInt = (s: string) => /^\d+$/.test(s);
const clamp = (n: number, lo: number, hi: number) =>
  Math.min(hi, Math.max(lo, n));

const DEFAULT_STATE: BuilderState = {
  freq: "daily",
  hour: 9,
  minute: 0,
  days: [1, 2, 3, 4, 5],
  dom: 1,
  nMinutes: 30,
  nHours: 2,
};

/** Строит cron-выражение (5 полей) из состояния конструктора. */
const buildCron = (s: BuilderState): string => {
  switch (s.freq) {
    case "daily":
      return `${s.minute} ${s.hour} * * *`;
    case "weekly": {
      const dow = [...s.days].sort((a, b) => a - b).join(",") || "*";
      return `${s.minute} ${s.hour} * * ${dow}`;
    }
    case "monthly":
      return `${s.minute} ${s.hour} ${s.dom} * *`;
    case "hourly":
      return `${s.minute} * * * *`;
    case "everyMinutes":
      return `*/${s.nMinutes} * * * *`;
    case "everyHours":
      return `0 */${s.nHours} * * *`;
  }
};

/** Парсит список дней недели cron (`1-5`, `1,3,5`) в числа 0–6 либо null. */
const parseDow = (s: string): number[] | null => {
  const out = new Set<number>();
  for (const tok of s.split(",")) {
    const range = tok.match(/^(\d+)-(\d+)$/);
    if (range) {
      const a = +range[1];
      const b = +range[2];
      if (a > b || b > 7) return null;
      for (let i = a; i <= b; i++) out.add(i % 7);
      continue;
    }
    if (/^\d+$/.test(tok)) {
      const v = +tok;
      if (v > 7) return null;
      out.add(v % 7);
      continue;
    }
    return null;
  }
  return [...out].sort((a, b) => a - b);
};

/** Пытается распознать cron как шаблон конструктора. null → нераспознан. */
const parseCron = (value: string): BuilderState | null => {
  const parts = value.trim().split(/\s+/);
  if (parts.length !== 5) return null;
  const [m, h, dom, mon, dow] = parts;
  if (mon !== "*") return null;

  const everyMin = m.match(/^\*\/(\d+)$/);
  if (everyMin && h === "*" && dom === "*" && dow === "*") {
    return { ...DEFAULT_STATE, freq: "everyMinutes", nMinutes: +everyMin[1] };
  }
  const everyHour = h.match(/^\*\/(\d+)$/);
  if (everyHour && m === "0" && dom === "*" && dow === "*") {
    return { ...DEFAULT_STATE, freq: "everyHours", nHours: +everyHour[1] };
  }
  if (isInt(m) && h === "*" && dom === "*" && dow === "*") {
    return { ...DEFAULT_STATE, freq: "hourly", minute: +m };
  }
  if (!isInt(m) || !isInt(h)) return null;
  const base = { ...DEFAULT_STATE, hour: +h, minute: +m };
  if (dom === "*" && dow === "*") return { ...base, freq: "daily" };
  if (isInt(dom) && dow === "*") {
    return { ...base, freq: "monthly", dom: +dom };
  }
  if (dom === "*") {
    const days = parseDow(dow);
    if (days && days.length) return { ...base, freq: "weekly", days };
  }
  return null;
};

const describeDays = (days: number[]): string => {
  const set = new Set(days);
  const eq = (arr: number[]) =>
    arr.length === set.size && arr.every((v) => set.has(v));
  if (eq([0, 1, 2, 3, 4, 5, 6])) return "каждый день";
  if (eq([1, 2, 3, 4, 5])) return "по будням";
  if (eq([0, 6])) return "по выходным";
  const names = WEEKDAYS.filter((d) => set.has(d.value)).map((d) => d.short);
  return names.length ? `по ${names.join(", ")}` : "по выбранным дням";
};

/** Человекочитаемое описание состояния конструктора на русском. */
const describe = (s: BuilderState): string => {
  const time = `${pad(s.hour)}:${pad(s.minute)}`;
  switch (s.freq) {
    case "daily":
      return `Каждый день в ${time}`;
    case "weekly": {
      if (!s.days.length) return "Выберите дни недели";
      const text = `${describeDays(s.days)} в ${time}`;
      return text.charAt(0).toUpperCase() + text.slice(1);
    }
    case "monthly":
      return `Ежемесячно ${s.dom}-го числа в ${time}`;
    case "hourly":
      return `Каждый час в :${pad(s.minute)}`;
    case "everyMinutes":
      return `Каждые ${s.nMinutes} мин.`;
    case "everyHours":
      return `Каждые ${s.nHours} ч. (в :00)`;
  }
};

const capitalize = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/**
 * Человекочитаемое описание произвольного cron. Для шаблонов конструктора —
 * свои аккуратные формулировки, для остального — cronstrue (ru).
 * null → выражение не распознано (невалидно).
 */
export const describeCron = (value: string): string | null => {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = parseCron(trimmed);
  if (parsed) return describe(parsed);
  try {
    return capitalize(
      cronstrue.toString(trimmed, {
        locale: "ru",
        use24HourTimeFormat: true,
        throwExceptionOnParseError: true,
      }),
    );
  } catch {
    return null;
  }
};

export interface CronBuilderProps {
  value: string;
  onChange: (cron: string) => void;
}

const CronBuilder: React.FC<CronBuilderProps> = ({ value, onChange }) => {
  // Режим и состояние инициализируются один раз из value (диалог монтирует
  // компонент заново при каждом открытии).
  const initial = useRef(parseCron(value));
  const [mode, setMode] = useState<"builder" | "expert">(
    initial.current || !value.trim() ? "builder" : "expert",
  );
  const [state, setState] = useState<BuilderState>(
    initial.current ?? DEFAULT_STATE,
  );
  const [raw, setRaw] = useState(value);

  // Конструктор — источник истины: эмитим cron при каждом изменении состояния.
  useEffect(() => {
    if (mode === "builder") onChange(buildCron(state));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state, mode]);

  const patch = (p: Partial<BuilderState>) =>
    setState((prev) => ({ ...prev, ...p }));

  const toggleDay = (day: number) => {
    setState((prev) => {
      const has = prev.days.includes(day);
      const days = has
        ? prev.days.filter((d) => d !== day)
        : [...prev.days, day];
      return { ...prev, days };
    });
  };

  const switchMode = (next: "builder" | "expert") => {
    if (next === mode) return;
    if (next === "expert") {
      // Переносим текущий cron в raw-поле
      setRaw(buildCron(state));
    } else {
      // Пытаемся разобрать raw в конструктор; иначе берём текущее состояние
      const parsed = parseCron(raw);
      if (parsed) setState(parsed);
    }
    setMode(next);
  };

  const onRawChange = (v: string) => {
    setRaw(v);
    onChange(v);
  };

  const rawDescription = describeCron(raw);
  const rawInvalid = raw.trim().length > 0 && rawDescription === null;

  return (
    <div className="space-y-3 rounded-lg border border-border p-3">
      {/* Переключатель режима */}
      <div className="inline-flex rounded-md border border-border p-0.5">
        {(
          [
            ["builder", "Конструктор", Wand2],
            ["expert", "Эксперт", Code2],
          ] as const
        ).map(([key, label, Icon]) => (
          <button
            key={key}
            type="button"
            onClick={() => switchMode(key)}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-[5px] px-3 py-1 text-sm transition-colors",
              mode === key
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <Icon className="size-3.5" />
            {label}
          </button>
        ))}
      </div>

      {mode === "builder" ? (
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label>Частота</Label>
            <Select
              value={state.freq}
              onValueChange={(v) => patch({ freq: v as Frequency })}
            >
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent style={{ zIndex: 9999 }}>
                {(Object.keys(FREQ_LABELS) as Frequency[]).map((f) => (
                  <SelectItem key={f} value={f}>
                    {FREQ_LABELS[f]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {state.freq === "weekly" && (
            <div className="space-y-1.5">
              <Label>Дни недели</Label>
              <div className="flex flex-wrap gap-1.5">
                {WEEKDAYS.map((d) => (
                  <Badge
                    key={d.value}
                    variant={
                      state.days.includes(d.value) ? "default" : "outline"
                    }
                    className="cursor-pointer select-none"
                    onClick={() => toggleDay(d.value)}
                  >
                    {d.short}
                  </Badge>
                ))}
              </div>
            </div>
          )}

          {state.freq === "monthly" && (
            <div className="space-y-1.5">
              <Label htmlFor="cron-dom">Число месяца</Label>
              <Input
                id="cron-dom"
                type="number"
                min={1}
                max={31}
                value={state.dom}
                onChange={(e) =>
                  patch({ dom: clamp(+e.target.value || 1, 1, 31) })
                }
                className="w-24"
              />
            </div>
          )}

          {state.freq === "everyMinutes" && (
            <div className="space-y-1.5">
              <Label htmlFor="cron-nmin">Интервал, минут</Label>
              <Input
                id="cron-nmin"
                type="number"
                min={1}
                max={59}
                value={state.nMinutes}
                onChange={(e) =>
                  patch({ nMinutes: clamp(+e.target.value || 1, 1, 59) })
                }
                className="w-24"
              />
            </div>
          )}

          {state.freq === "everyHours" && (
            <div className="space-y-1.5">
              <Label htmlFor="cron-nhour">Интервал, часов</Label>
              <Input
                id="cron-nhour"
                type="number"
                min={1}
                max={23}
                value={state.nHours}
                onChange={(e) =>
                  patch({ nHours: clamp(+e.target.value || 1, 1, 23) })
                }
                className="w-24"
              />
            </div>
          )}

          {(state.freq === "daily" ||
            state.freq === "weekly" ||
            state.freq === "monthly") && (
            <div className="space-y-1.5">
              <Label>Время</Label>
              <div className="flex items-center gap-2">
                <Select
                  value={String(state.hour)}
                  onValueChange={(v) => patch({ hour: +v })}
                >
                  <SelectTrigger className="w-20">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent style={{ zIndex: 9999 }} className="max-h-60">
                    {Array.from({ length: 24 }, (_, i) => i).map((h) => (
                      <SelectItem key={h} value={String(h)}>
                        {pad(h)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <span className="text-muted-foreground">:</span>
                <Select
                  value={String(state.minute)}
                  onValueChange={(v) => patch({ minute: +v })}
                >
                  <SelectTrigger className="w-20">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent style={{ zIndex: 9999 }} className="max-h-60">
                    {Array.from({ length: 60 }, (_, i) => i).map((m) => (
                      <SelectItem key={m} value={String(m)}>
                        {pad(m)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          )}

          {state.freq === "hourly" && (
            <div className="space-y-1.5">
              <Label htmlFor="cron-min">Минута часа</Label>
              <Input
                id="cron-min"
                type="number"
                min={0}
                max={59}
                value={state.minute}
                onChange={(e) =>
                  patch({ minute: clamp(+e.target.value || 0, 0, 59) })
                }
                className="w-24"
              />
            </div>
          )}

          <div className="flex items-center justify-between gap-2 border-t border-border pt-2 text-xs">
            <span className="font-medium">{describe(state)}</span>
            <code className="rounded bg-muted px-1.5 py-0.5 text-muted-foreground">
              {buildCron(state)}
            </code>
          </div>
        </div>
      ) : (
        <div className="space-y-2">
          <Label htmlFor="cron-raw">Cron-выражение</Label>
          <Input
            id="cron-raw"
            value={raw}
            onChange={(e) => onRawChange(e.target.value)}
            placeholder="0 9 * * 1"
            className={cn("font-mono", rawInvalid && "border-destructive")}
          />
          <div className="flex items-center justify-between gap-2 text-xs">
            <span
              className={cn(
                "text-muted-foreground",
                rawInvalid && "text-destructive",
              )}
            >
              {raw.trim()
                ? (rawDescription ?? "Не удалось распознать cron-выражение")
                : "минута час день месяц день_недели"}
            </span>
          </div>
        </div>
      )}
    </div>
  );
};

export default CronBuilder;
