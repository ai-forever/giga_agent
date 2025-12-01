import React, { useEffect, useState } from "react";
import axios from "axios";
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

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

  useEffect(() => {
    load();
  }, []);

  return (
    <div className="flex flex-col w-full p-4 gap-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Долгосрочная память</h1>
        <button
          className="inline-flex items-center rounded-md border px-3 py-1.5 text-sm hover:bg-accent"
          onClick={load}
          disabled={loading}
        >
          Обновить
        </button>
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
              </TableRow>
            ))}
          </TableBody>
          <TableCaption>
            Всего записей: {items.length}
          </TableCaption>
        </Table>
      )}
    </div>
  );
};

export default MemoriesPage;


