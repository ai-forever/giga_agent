"use client";

import type React from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
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
import { Trash2, MoreVertical } from "lucide-react";
import { Document } from "@langchain/core/documents";
import { format } from "date-fns";
import { Collection } from "@/types/collection";
import { useRagContext } from "@/components/rag/providers/RAG.tsx";
import { getCollectionName } from "@/components/rag/hooks/use-rag.tsx";

interface DocumentsTableProps {
  documents: Document[];
  selectedCollection: Collection;
  actionsDisabled: boolean;
}

export function DocumentsTable({
  documents,
  selectedCollection,
  actionsDisabled,
}: DocumentsTableProps) {
  const { deleteDocument } = useRagContext();
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Название документа</TableHead>
          <TableHead>Папка</TableHead>
          <TableHead>Дата загрузки</TableHead>
          <TableHead className="text-right">Действия</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {documents.length === 0 ? (
          <TableRow>
            <TableCell
              colSpan={4}
              className="text-muted-foreground text-center"
            >
              В этой папке нет документов.
            </TableCell>
          </TableRow>
        ) : (
          documents.map((doc) => (
            <TableRow key={doc.id}>
              <TableCell className="font-medium">{doc.metadata.name}</TableCell>
              <TableCell>
                <Badge variant="secondary">
                  {getCollectionName(selectedCollection.name)}
                </Badge>
              </TableCell>
              <TableCell>
                {format(new Date(doc.metadata.created_at), "MM/dd/yyyy h:mm a")}
              </TableCell>
              <TableCell className="text-right">
                <AlertDialog>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button variant="ghost" size="icon">
                        <MoreVertical className="h-4 w-4" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <AlertDialogTrigger asChild>
                        <DropdownMenuItem
                          className="text-destructive"
                          disabled={actionsDisabled}
                        >
                          <Trash2 className="mr-2 h-4 w-4" />
                          Удалить
                        </DropdownMenuItem>
                      </AlertDialogTrigger>
                    </DropdownMenuContent>
                  </DropdownMenu>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>Вы уверены?</AlertDialogTitle>
                      <AlertDialogDescription>
                        Это действие невозможно отменить. Документ будет
                        безвозвратно удалён
                        <span className="font-semibold">
                          {" "}
                          {doc.metadata.name}
                        </span>
                        .
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>Отмена</AlertDialogCancel>
                      <AlertDialogAction
                        onClick={async () =>
                          await deleteDocument(doc.metadata.file_id)
                        }
                        className="bg-destructive hover:bg-destructive/90 text-white"
                        disabled={actionsDisabled}
                      >
                        Удалить
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              </TableCell>
            </TableRow>
          ))
        )}
      </TableBody>
    </Table>
  );
}
