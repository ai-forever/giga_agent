import React, { useCallback, useEffect, useState } from "react";
import { CalendarClock, Loader2 } from "lucide-react";
import { toast } from "sonner";

import { useConfirm } from "@/components/providers/confirm.tsx";
import { refreshThreads } from "@/lib/events";
import {
  deleteScheduledTask,
  getScheduledTask,
  runScheduledTask,
  type ScheduledTask,
  updateScheduledTask,
} from "./api";
import { taskDisplayName, TaskFormDialog, TaskRow } from "./shared";

/**
 * Generative-UI card shown in the chat when the agent successfully scheduled a
 * task via `schedule_task`. Renders the same scheduler row (with the same
 * actions) under a "Планирование задачи" label, fetching live task state by id.
 */
const SchedulerTaskChatCard: React.FC<{ taskId: string }> = ({ taskId }) => {
  const confirm = useConfirm();
  const [task, setTask] = useState<ScheduledTask | null>(null);
  const [loading, setLoading] = useState(true);
  const [missing, setMissing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const data = await getScheduledTask(taskId);
      setTask(data);
      setMissing(false);
    } catch {
      setMissing(true);
    } finally {
      setLoading(false);
    }
  }, [taskId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleToggleEnabled = async (enabled: boolean) => {
    if (!task) return;
    setBusy(true);
    try {
      await updateScheduledTask(task.id, { is_enabled: enabled });
      await refresh();
    } catch {
      // handled globally
    } finally {
      setBusy(false);
    }
  };

  const handleRunNow = async () => {
    if (!task) return;
    setBusy(true);
    try {
      await runScheduledTask(task.id);
      toast.success("Тестовый запуск запущен");
      // The run creates a fresh scheduled thread in the background; refresh the
      // sidebar chat list shortly after so it shows up.
      setTimeout(() => refreshThreads(), 3000);
    } catch {
      // handled globally
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async () => {
    if (!task) return;
    if (
      !(await confirm({
        title: "Удалить задачу?",
        description: `Удалить «${taskDisplayName(task)}»?`,
        confirmText: "Удалить",
        variant: "destructive",
      }))
    ) {
      return;
    }
    setBusy(true);
    try {
      await deleteScheduledTask(task.id);
      toast.success("Задача удалена");
      setMissing(true);
      setTask(null);
    } catch {
      // handled globally
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" /> Загрузка задачи...
      </div>
    );
  }

  if (missing || !task) {
    return (
      <div className="text-sm text-muted-foreground">
        Запланированная задача недоступна.
      </div>
    );
  }

  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
        <CalendarClock className="size-3.5" />
        Планирование задачи
      </div>
      <TaskRow
        task={task}
        busy={busy}
        onToggleEnabled={(v) => void handleToggleEnabled(v)}
        onRunNow={() => void handleRunNow()}
        onEdit={() => setDialogOpen(true)}
        onDelete={() => void handleDelete()}
      />
      <TaskFormDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        editingTask={task}
        onSaved={() => void refresh()}
      />
    </div>
  );
};

export default SchedulerTaskChatCard;
