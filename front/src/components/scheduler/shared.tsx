import React, { useEffect, useMemo, useState } from "react";
import { Loader2, Pencil, Rocket, Trash2, Users } from "lucide-react";
import { toast } from "sonner";

import { API_AGENT_PREFIX } from "@/config.ts";
import { apiClient } from "@/lib/api-client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import TimezoneSelect from "@/components/ui/timezone-select";
import DateTimePicker from "@/components/ui/datetime-picker";
import CronBuilder, { describeCron } from "./cron-builder";
import type {
  ChannelBotResponse,
  ChannelContactResponse,
} from "@/components/settings-page/forms/types";
import {
  createScheduledTask,
  type DeliveryTarget,
  type ScheduledTask,
  type ScheduledTaskKind,
  updateScheduledTask,
} from "./api";

export const STATUS_LABELS: Record<string, string> = {
  pending: "Запланирована",
  running: "Выполняется",
  done: "Выполнена",
  done_no_delivery: "Выполнена (без доставки)",
  partially_failed: "Частично доставлена",
  failed: "Ошибка",
  cancelled: "Отменена",
};

export const statusVariant = (
  status: string,
): "default" | "secondary" | "destructive" | "outline" => {
  if (status === "failed") return "destructive";
  if (status === "done") return "default";
  if (status === "running" || status === "pending") return "secondary";
  return "outline";
};

/** Terminal statuses of a one-off run — the task has finished for good. */
const TERMINAL_STATUSES = new Set([
  "done",
  "done_no_delivery",
  "partially_failed",
  "failed",
  "cancelled",
]);

/**
 * A task counts as "completed" when it's a one-off run that reached a terminal
 * status. Cron tasks keep recurring, so they always stay in the scheduled tab.
 */
export const isCompletedTask = (task: ScheduledTask): boolean =>
  task.kind === "once" && TERMINAL_STATUSES.has(task.status);

const targetKey = (t: DeliveryTarget): string =>
  `${t.bot_id}|${t.external_chat_id}|${t.external_user_id ?? ""}`;

export const formatDateTime = (value: string | null): string => {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
};

export const taskDisplayName = (task: ScheduledTask): string =>
  task.name?.trim() || `Запланированная задача: ${task.prompt.slice(0, 100)}`;

/** Человекочитаемое описание расписания задачи для строки под названием. */
export const scheduleDescription = (task: ScheduledTask): string => {
  if (task.kind === "once") return "Разовый запуск";
  const cron = task.cron?.trim();
  if (!cron) return "Периодический запуск";
  return describeCron(cron) ?? `cron: ${cron}`;
};

const toDatetimeLocalValue = (iso: string | null): string => {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(
    d.getHours(),
  )}:${pad(d.getMinutes())}`;
};

const contactLabel = (c: ChannelContactResponse): string => {
  if (c.chat_title?.trim()) return c.chat_title.trim();
  const name = [c.first_name, c.last_name]
    .map((v) => v?.trim())
    .filter(Boolean)
    .join(" ");
  if (name) return name;
  if (c.username?.trim()) return `@${c.username.trim()}`;
  return c.external_chat_id;
};

const isGroupContact = (c: ChannelContactResponse): boolean =>
  c.chat_type === "group" || c.chat_type === "supergroup";

const botLabel = (bot: ChannelBotResponse): string =>
  bot.bot_username?.trim()
    ? `@${bot.bot_username.trim()}`
    : `${bot.channel_type} • ${bot.id.slice(0, 8)}`;

const browserTimezone = (): string => {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone ?? "";
  } catch {
    return "";
  }
};

interface TargetPickerProps {
  selected: DeliveryTarget[];
  onChange: (targets: DeliveryTarget[]) => void;
}

const TargetPicker: React.FC<TargetPickerProps> = ({ selected, onChange }) => {
  const [bots, setBots] = useState<ChannelBotResponse[]>([]);
  const [contactsByBot, setContactsByBot] = useState<
    Record<string, ChannelContactResponse[]>
  >({});
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      try {
        const botList = await apiClient.get<ChannelBotResponse[]>(
          `${API_AGENT_PREFIX}/channels`,
        );
        if (cancelled) return;
        setBots(botList);
        const entries = await Promise.all(
          botList.map(async (bot) => {
            try {
              const contacts = await apiClient.get<ChannelContactResponse[]>(
                `${API_AGENT_PREFIX}/channels/${bot.id}/contacts`,
              );
              return [bot.id, contacts.filter((c) => c.is_approved)] as const;
            } catch {
              return [bot.id, []] as const;
            }
          }),
        );
        if (!cancelled) {
          setContactsByBot(Object.fromEntries(entries));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const selectedKeys = useMemo(
    () => new Set(selected.map(targetKey)),
    [selected],
  );

  const toggle = (bot: ChannelBotResponse, c: ChannelContactResponse) => {
    const target: DeliveryTarget = {
      bot_id: bot.id,
      external_chat_id: c.external_chat_id,
      external_user_id: c.external_user_id,
    };
    const key = targetKey(target);
    if (selectedKeys.has(key)) {
      onChange(selected.filter((t) => targetKey(t) !== key));
    } else {
      onChange([...selected, target]);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" /> Загрузка получателей...
      </div>
    );
  }

  const hasContacts = bots.some(
    (bot) => (contactsByBot[bot.id]?.length ?? 0) > 0,
  );

  if (!hasContacts) {
    return (
      <p className="text-sm text-muted-foreground">
        Нет подтверждённых контактов. Результат уйдёт получателям по умолчанию
        (настраиваются в разделе «Настройки → Каналы»).
      </p>
    );
  }

  return (
    <div className="space-y-3 max-h-48 overflow-auto rounded-lg border border-border p-3">
      {bots.map((bot) => {
        const contacts = contactsByBot[bot.id] ?? [];
        if (contacts.length === 0) return null;
        return (
          <div key={bot.id} className="space-y-1.5">
            <div className="text-xs font-medium text-muted-foreground">
              {botLabel(bot)}
            </div>
            <div className="flex flex-wrap gap-2">
              {contacts.map((c) => {
                const key = targetKey({
                  bot_id: bot.id,
                  external_chat_id: c.external_chat_id,
                  external_user_id: c.external_user_id,
                });
                const isSelected = selectedKeys.has(key);
                return (
                  <Badge
                    key={c.id}
                    variant={isSelected ? "default" : "outline"}
                    className="cursor-pointer gap-1"
                    onClick={() => toggle(bot, c)}
                    title={isGroupContact(c) ? "Групповой чат" : undefined}
                  >
                    {isGroupContact(c) && <Users className="size-3" />}
                    {contactLabel(c)}
                  </Badge>
                );
              })}
            </div>
          </div>
        );
      })}
      <p className="text-xs text-muted-foreground">
        Ничего не выбрано — результат уйдёт получателям по умолчанию.
      </p>
    </div>
  );
};

interface TaskFormState {
  name: string;
  prompt: string;
  kind: ScheduledTaskKind;
  runAtLocal: string;
  cron: string;
  timezone: string;
  targets: DeliveryTarget[];
  isEnabled: boolean;
}

const formFromTask = (task: ScheduledTask | null): TaskFormState => {
  if (!task) {
    return {
      name: "",
      prompt: "",
      kind: "once",
      runAtLocal: "",
      cron: "",
      timezone: browserTimezone(),
      targets: [],
      isEnabled: true,
    };
  }
  return {
    name: task.name ?? "",
    prompt: task.prompt,
    kind: task.kind,
    runAtLocal: task.kind === "once" ? toDatetimeLocalValue(task.run_at) : "",
    cron: task.cron ?? "",
    timezone: task.timezone ?? "",
    targets: task.targets ?? [],
    isEnabled: task.is_enabled,
  };
};

interface TaskFormDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Task being edited, or null to create a new one. */
  editingTask: ScheduledTask | null;
  onSaved: () => void;
}

export const TaskFormDialog: React.FC<TaskFormDialogProps> = ({
  open,
  onOpenChange,
  editingTask,
  onSaved,
}) => {
  const [form, setForm] = useState<TaskFormState>(() =>
    formFromTask(editingTask),
  );
  const [saving, setSaving] = useState(false);

  // Reset form whenever the dialog opens for a (possibly different) task.
  useEffect(() => {
    if (open) {
      setForm(formFromTask(editingTask));
    }
  }, [open, editingTask]);

  const handleSubmit = async () => {
    if (!form.prompt.trim()) {
      toast.error("Заполните текст задачи");
      return;
    }
    if (form.kind === "once" && !form.runAtLocal) {
      toast.error("Укажите дату и время запуска");
      return;
    }
    if (form.kind === "cron" && !form.cron.trim()) {
      toast.error("Укажите cron-выражение");
      return;
    }

    const payload = {
      name: form.name.trim() || null,
      prompt: form.prompt.trim(),
      kind: form.kind,
      cron: form.kind === "cron" ? form.cron.trim() : null,
      timezone: form.timezone.trim() || null,
      run_at:
        form.kind === "once" ? new Date(form.runAtLocal).toISOString() : null,
      targets: form.targets,
      is_enabled: form.isEnabled,
    };

    setSaving(true);
    try {
      if (editingTask) {
        await updateScheduledTask(editingTask.id, payload);
        toast.success("Задача обновлена");
      } else {
        await createScheduledTask(payload);
        toast.success("Задача создана");
      }
      onOpenChange(false);
      onSaved();
    } catch {
      // handled globally
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-auto sm:max-w-[560px]">
        <DialogHeader>
          <DialogTitle>
            {editingTask ? "Изменить задачу" : "Новая задача"}
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="task-name">Название (необязательно)</Label>
            <Input
              id="task-name"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="Например: Утренняя сводка"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="task-prompt">Задача агенту</Label>
            <Textarea
              id="task-prompt"
              value={form.prompt}
              onChange={(e) => setForm({ ...form, prompt: e.target.value })}
              placeholder="Опиши, что нужно сделать..."
              rows={3}
            />
          </div>
          <div className="space-y-1.5">
            <Label>Расписание</Label>
            <Select
              value={form.kind}
              onValueChange={(v) =>
                setForm({ ...form, kind: v as ScheduledTaskKind })
              }
            >
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent style={{ zIndex: 9999 }}>
                <SelectItem value="once">Разово</SelectItem>
                <SelectItem value="cron">Периодически (cron)</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {form.kind === "once" ? (
            <div className="space-y-1.5">
              <Label htmlFor="task-runat">Дата и время</Label>
              <DateTimePicker
                id="task-runat"
                value={form.runAtLocal}
                onChange={(v) => setForm({ ...form, runAtLocal: v })}
              />
            </div>
          ) : (
            <div className="space-y-3">
              <CronBuilder
                value={form.cron}
                onChange={(cron) => setForm({ ...form, cron })}
              />
              <div className="space-y-1.5">
                <Label htmlFor="task-tz">Таймзона</Label>
                <TimezoneSelect
                  id="task-tz"
                  value={form.timezone}
                  onValueChange={(v) => setForm({ ...form, timezone: v })}
                />
              </div>
            </div>
          )}
          <div className="space-y-1.5">
            <Label>Получатели результата</Label>
            <TargetPicker
              selected={form.targets}
              onChange={(targets) => setForm({ ...form, targets })}
            />
          </div>
          <div className="flex gap-2 pt-2">
            <Button onClick={() => void handleSubmit()} disabled={saving}>
              {saving ? (
                <>
                  <Loader2 className="mr-2 size-4 animate-spin" />
                  Сохранение...
                </>
              ) : editingTask ? (
                "Сохранить"
              ) : (
                "Создать"
              )}
            </Button>
            <Button
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={saving}
            >
              Отмена
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
};

interface TaskRowProps {
  task: ScheduledTask;
  busy: boolean;
  onToggleEnabled: (enabled: boolean) => void;
  onRunNow: () => void;
  onEdit: () => void;
  onDelete: () => void;
}

export const TaskRow: React.FC<TaskRowProps> = ({
  task,
  busy,
  onToggleEnabled,
  onRunNow,
  onEdit,
  onDelete,
}) => {
  return (
    <div className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-border bg-card px-4 py-3">
      <div className="min-w-0 flex-1">
        <span className="font-medium">{taskDisplayName(task)}</span>
        <div className="mt-0.5 text-xs text-muted-foreground">
          {scheduleDescription(task)}
        </div>
        <div className="mt-1 text-xs text-muted-foreground">
          Следующий запуск: {formatDateTime(task.run_at)}
          {task.targets.length > 0
            ? ` • получателей: ${task.targets.length}`
            : " • получатели по умолчанию"}
        </div>
        {task.last_error && (
          <div className="mt-1 text-xs text-destructive">{task.last_error}</div>
        )}
      </div>
      <div className="flex items-center gap-2">
        <Switch
          checked={task.is_enabled}
          disabled={busy}
          onCheckedChange={(v) => onToggleEnabled(v)}
        />
        <Button
          variant="ghost"
          size="icon"
          onClick={onRunNow}
          disabled={busy}
          title="Запустить сейчас (тестовый запуск)"
        >
          {busy ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <Rocket className="size-4" />
          )}
        </Button>
        <Button variant="outline" size="sm" onClick={onEdit} disabled={busy}>
          <Pencil className="mr-2 size-4" />
          Изменить
        </Button>
        <Button
          variant="ghost"
          size="icon"
          onClick={onDelete}
          disabled={busy}
          title="Удалить"
        >
          {busy ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <Trash2 className="size-4 text-destructive" />
          )}
        </Button>
      </div>
    </div>
  );
};
