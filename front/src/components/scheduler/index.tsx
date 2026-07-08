import React, { useCallback, useEffect, useState } from "react";
import { Clock, Loader2, Plus } from "lucide-react";
import { toast } from "sonner";

import { useConfirm } from "@/components/providers/confirm.tsx";
import { refreshThreads } from "@/lib/events";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  deleteScheduledTask,
  listScheduledTasks,
  runScheduledTask,
  type ScheduledTask,
  updateScheduledTask,
} from "./api";
import {
  isCompletedTask,
  taskDisplayName,
  TaskFormDialog,
  TaskRow,
} from "./shared";

const SchedulerPage: React.FC = () => {
  const confirm = useConfirm();
  const [tasks, setTasks] = useState<ScheduledTask[]>([]);
  const [loading, setLoading] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingTask, setEditingTask] = useState<ScheduledTask | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const fetchTasks = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listScheduledTasks();
      setTasks(data);
    } catch {
      // handled globally
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchTasks();
  }, [fetchTasks]);

  const openCreate = () => {
    setEditingTask(null);
    setDialogOpen(true);
  };

  const openEdit = (task: ScheduledTask) => {
    setEditingTask(task);
    setDialogOpen(true);
  };

  const handleToggleEnabled = async (task: ScheduledTask, enabled: boolean) => {
    setBusyId(task.id);
    try {
      await updateScheduledTask(task.id, { is_enabled: enabled });
      await fetchTasks();
    } catch {
      // handled globally
    } finally {
      setBusyId(null);
    }
  };

  const handleRunNow = async (task: ScheduledTask) => {
    setBusyId(task.id);
    try {
      await runScheduledTask(task.id);
      toast.success("Тестовый запуск запущен");
      // The run creates a fresh scheduled thread in the background; refresh the
      // sidebar chat list shortly after so it shows up.
      setTimeout(() => refreshThreads(), 3000);
    } catch {
      // handled globally
    } finally {
      setBusyId(null);
    }
  };

  const handleDelete = async (task: ScheduledTask) => {
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
    setBusyId(task.id);
    try {
      await deleteScheduledTask(task.id);
      toast.success("Задача удалена");
      await fetchTasks();
    } catch {
      // handled globally
    } finally {
      setBusyId(null);
    }
  };

  const scheduledTasks = tasks.filter((t) => !isCompletedTask(t));
  const completedTasks = tasks.filter((t) => isCompletedTask(t));

  const renderTask = (task: ScheduledTask) => (
    <TaskRow
      key={task.id}
      task={task}
      busy={busyId === task.id}
      onToggleEnabled={(v) => void handleToggleEnabled(task, v)}
      onRunNow={() => void handleRunNow(task)}
      onEdit={() => openEdit(task)}
      onDelete={() => void handleDelete(task)}
    />
  );

  const renderList = (
    list: ScheduledTask[],
    emptyText: string,
    emptyHint: string,
  ) => {
    if (loading) {
      return (
        <div className="flex items-center justify-center py-10 text-muted-foreground">
          <Loader2 className="mr-2 size-4 animate-spin" />
          Загрузка...
        </div>
      );
    }
    if (list.length === 0) {
      return (
        <div className="rounded-xl border border-dashed border-border bg-muted/20 px-5 py-10 text-center">
          <p className="font-medium">{emptyText}</p>
          <p className="mt-1 text-sm text-muted-foreground">{emptyHint}</p>
        </div>
      );
    }
    return <div className="space-y-3">{list.map(renderTask)}</div>;
  };

  return (
    <div className="w-full flex lg:p-5 p-0 lg:mt-0 bg-card">
      <div className="flex flex-col max-w-[1000px] mx-auto h-full flex-1 overflow-hidden">
        <div className="flex items-center justify-between gap-4 p-6 border-b border-border">
          <div className="flex items-center gap-2">
            <Clock className="size-5" />
            <h1 className="text-xl font-semibold">Планировщик</h1>
          </div>
          <Button onClick={openCreate} size="sm">
            <Plus className="mr-2 size-4" />
            Новая задача
          </Button>
        </div>

        <Tabs defaultValue="scheduled" className="flex-1 overflow-hidden gap-0">
          <div className="px-6 pt-6">
            <TabsList>
              <TabsTrigger value="scheduled">
                Запланированные задачи
              </TabsTrigger>
              <TabsTrigger value="completed">Выполненные</TabsTrigger>
            </TabsList>
          </div>

          <TabsContent value="scheduled" className="overflow-auto p-6">
            {renderList(
              scheduledTasks,
              "Запланированных задач пока нет",
              "Создайте отложенную или периодическую задачу — её результат будет отправлен в выбранные каналы.",
            )}
          </TabsContent>
          <TabsContent value="completed" className="overflow-auto p-6">
            {renderList(
              completedTasks,
              "Выполненных задач пока нет",
              "Здесь появятся разовые задачи после того, как они отработают.",
            )}
          </TabsContent>
        </Tabs>
      </div>

      <TaskFormDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        editingTask={editingTask}
        onSaved={() => void fetchTasks()}
      />
    </div>
  );
};

export default SchedulerPage;
