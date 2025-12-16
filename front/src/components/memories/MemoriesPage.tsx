import React, { useEffect, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { X } from "lucide-react";
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Card, CardContent } from "../ui/card";

type MemoryItem = {
  id?: string;
  memory?: string;
  created_at?: string;
  last_accessed_at?: string;
  [key: string]: any;
};

const normalizeMemories = (data: any): MemoryItem[] => {
  if (Array.isArray(data)) return data as MemoryItem[];
  if (data && Array.isArray(data.results)) return data.results as MemoryItem[];
  return [];
};

const formatDate = (value?: string) => {
  if (!value) return "";
  try {
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return value;
    return d.toLocaleString();
  } catch {
    return value;
  }
};

const MemoriesPage: React.FC = () => {
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [items, setItems] = useState<MemoryItem[]>([]);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await axios.get("/api/memories");
      setItems(normalizeMemories(resp.data));
    } catch (e: any) {
      setError(e?.message ?? "Не удалось получить данные");
    } finally {
      setLoading(false);
    }
  };

  const deleteAll = async () => {
    try {
      await axios.delete("/api/memories");
      toast.success("Все записи успешно удалены");
      load();
    } catch (e) {
      toast.error("Не удалось удалить записи", {
        richColors: true,
        description: "Не удалось удалить все записи. Попробуйте ещё раз.",
      });
    }
  };

  const deleteOne = async (id: string) => {
    try {
      await axios.delete(`/api/memories/${id}`);
      toast.success("Запись успешно удалена");
      load();
    } catch (e) {
      toast.error("Не удалось удалить запись", {
        richColors: true,
        description: "Не удалось удалить запись. Попробуйте ещё раз.",
      });
    }
  };

  useEffect(() => {
    load();
  }, []);

  return (
    <div className="container mx-auto p-5 w-full flex lg:p-5 p-0 lg:mt-0 mt-[75px]">
      <Card className="bg-card/80 max-w-[900px] w-full mx-auto border-0 shadow-md">
      <CardContent className="flex flex-col space-y-6 px-6">

      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Долгосрочная память</h1>
        <div className="flex gap-2">
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button variant="destructive" disabled={loading || items.length === 0}>
                Удалить все
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Вы уверены?</AlertDialogTitle>
                <AlertDialogDescription>
                  Это действие невозможно отменить. Все записи памяти будут
                  безвозвратно удалены.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Отмена</AlertDialogCancel>
                <AlertDialogAction
                  onClick={deleteAll}
                  className="bg-destructive hover:bg-destructive/90 text-white"
                >
                  Удалить
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
          <button
            className="inline-flex items-center rounded-md border px-3 py-1.5 text-sm hover:bg-accent cursor-pointer"
            onClick={load}
            disabled={loading}
          >
            Обновить
          </button>
        </div>
      </div>

      {loading && <div>Загрузка...</div>}
      {error && !loading && (
        <div className="text-red-500">Ошибка: {error}</div>
      )}
      {!loading && !error && items.length === 0 && (
        <div className="text-muted-foreground">Нет записей памяти.</div>
      )}

      {!loading && !error && items.length > 0 && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Память</TableHead>
              <TableHead>Дата</TableHead>
              <TableHead>ID</TableHead>
              <TableHead className="w-[50px]"></TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((it, idx) => (
              <TableRow key={it.id ?? idx}>
                <TableCell className="max-w-[800px] whitespace-normal break-words">
                  {it.memory ?? ""}
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {formatDate(it.created_at || it.last_accessed_at)}
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {it.id ?? ""}
                </TableCell>
                <TableCell>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 text-destructive/60 hover:text-destructive dark:hover:bg-transparent"
                    onClick={() => it.id && deleteOne(it.id)}
                  >
                    <X className="h-4 w-4" />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
          <TableCaption>
            Всего записей: {items.length}
          </TableCaption>
        </Table>
      )}
      </CardContent>
      </Card>
    </div>
  );
};

export default MemoriesPage;


