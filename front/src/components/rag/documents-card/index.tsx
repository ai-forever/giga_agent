"use client";

import type React from "react";
import { useState, useMemo, DragEvent } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Pagination,
  PaginationContent,
  PaginationItem,
  PaginationLink,
  PaginationNext,
  PaginationPrevious,
} from "@/components/ui/pagination";
import { Plus, FileUp, X } from "lucide-react";
import { DocumentsTable } from "./documents-table";
import { Collection } from "@/types/collection";
import { Skeleton } from "@/components/ui/skeleton";
import { toast } from "sonner";
import { getCollectionName } from "@/components/rag/hooks/use-rag.tsx";
import { useRagContext } from "@/components/rag/providers/RAG.tsx";

// Supported document types for RAG uploads. Must stay in sync with the backend
// document_processor HANDLERS (backend/giga_agent/modules/rag/services/document_processor.py).
const ACCEPTED_FILE_EXTENSIONS = [
  ".pdf",
  ".txt",
  ".md",
  ".markdown",
  ".html",
  ".doc",
  ".docx",
];
const ACCEPTED_MIME_TYPES = [
  "application/pdf",
  "text/plain",
  "text/markdown",
  "text/x-markdown",
  "text/html",
  "application/msword",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
];

const getFileExtension = (fileName: string) =>
  fileName.substring(fileName.lastIndexOf(".")).toLowerCase();

// A file is accepted if its MIME type is known, or — for types browsers often
// report with an empty MIME (e.g. .md) — if its extension is allowed.
const isSupportedFile = (file: File) =>
  ACCEPTED_MIME_TYPES.includes(file.type) ||
  ACCEPTED_FILE_EXTENSIONS.includes(getFileExtension(file.name));

interface DocumentsCardProps {
  selectedCollection: Collection | undefined;
  currentPage: number;
  setCurrentPage: React.Dispatch<React.SetStateAction<number>>;
}

export function DocumentsCard({
  selectedCollection,
  currentPage,
  setCurrentPage,
}: DocumentsCardProps) {
  const {
    documents,
    handleFileUpload: handleDocumentFileUpload,
    handleTextUpload: handleDocumentTextUpload,
  } = useRagContext();

  const itemsPerPage = 10;

  const [textInput, setTextInput] = useState("");
  const [stagedFiles, setStagedFiles] = useState<File[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [isDragging, setIsDragging] = useState(false);

  const filteredDocuments = useMemo(
    () =>
      documents.filter(
        (doc) => doc.metadata.collection === selectedCollection?.uuid,
      ),
    [documents, selectedCollection],
  );

  // Calculate pagination for documents
  const totalPages = Math.ceil(filteredDocuments.length / itemsPerPage);
  const currentDocuments = useMemo(
    () =>
      filteredDocuments.slice(
        (currentPage - 1) * itemsPerPage,
        currentPage * itemsPerPage,
      ),
    [filteredDocuments, currentPage, itemsPerPage],
  );

  // Handle adding files to staging
  const handleFiles = (files: File[] | null) => {
    if (!files?.length) return;

    const filteredFiles = files.filter(isSupportedFile);

    setStagedFiles((prevFiles) => [...prevFiles, ...filteredFiles]);
  };

  const handleFileSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
    if (event.target.files) {
      handleFiles(Array.from(event.target.files));
    }
  };

  const handleDragOver = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.stopPropagation();
    setIsDragging(true);
  };

  const handleDragLeave = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.stopPropagation();
    setIsDragging(false);
  };

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.stopPropagation();
    setIsDragging(false);

    const files = event.dataTransfer.files;
    const supportedFiles: File[] = [];
    const unsupportedFiles: File[] = [];

    for (const file of files) {
      if (isSupportedFile(file)) {
        supportedFiles.push(file);
      } else {
        unsupportedFiles.push(file);
      }
    }

    if (unsupportedFiles.length > 0) {
      const unsupportedNames = unsupportedFiles.map((f) => f.name).join(", ");
      toast.error(
        `Неподдерживаемые типы файлов: ${unsupportedNames}. Пожалуйста, используйте PDF, TXT, MD, DOC, DOCX или HTML.`,
        { richColors: true },
      );
    }

    if (supportedFiles.length > 0) {
      handleFiles(supportedFiles);
    }
  };

  // Handle removing a file from staging
  const removeStagedFile = (indexToRemove: number) => {
    setStagedFiles((prevFiles) =>
      prevFiles.filter((_, index) => index !== indexToRemove),
    );
  };

  // Handle uploading staged files (uses document hook)
  const handleUploadStagedFiles = async () => {
    if (!selectedCollection) {
      // Should ideally be handled by disabling the button, but good practice
      console.error("No collection selected for upload");
      return;
    }
    if (stagedFiles.length === 0) {
      // Should ideally be handled by hiding the button, but good practice
      console.warn("No files staged for upload");
      return;
    }

    setIsUploading(true);
    const loadingToast = toast.loading("Загрузка файлов", { richColors: true });
    // Convert File[] to FileList as expected by the hook
    const dataTransfer = new DataTransfer();
    stagedFiles.forEach((file) => dataTransfer.items.add(file));
    const fileList = dataTransfer.files;

    await handleDocumentFileUpload(fileList, selectedCollection.uuid);

    toast.success("Файлы успешно загружены", { richColors: true });
    setIsUploading(false);
    toast.dismiss(loadingToast);
    setStagedFiles([]); // Clear staged files after initiating upload
  };

  // Handle text upload (uses document hook)
  const handleTextUpload = async () => {
    if (!selectedCollection) {
      throw new Error("No collection selected");
    }

    if (textInput.trim()) {
      setIsUploading(true);
      const loadingToast = toast.loading("Загрузка текстового документа", {
        richColors: true,
      });
      await handleDocumentTextUpload(textInput, selectedCollection.uuid);
      setTextInput("");
      setIsUploading(false);
      toast.dismiss(loadingToast);
      toast.success("Текстовый документ успешно загружен", {
        richColors: true,
      });
    }
  };

  return (
    <Card className="shadow-(--shadow-s)">
      <CardHeader className="flex w-full items-center justify-between">
        <div className="flex flex-col gap-2">
          <CardTitle>
            Документы папки {getCollectionName(selectedCollection?.name)}
          </CardTitle>
          <CardDescription>Управляйте документами в этой папке</CardDescription>
        </div>
      </CardHeader>
      <CardContent>
        <div className="mb-6">
          <Tabs defaultValue="file">
            <TabsList className="mb-4">
              <TabsTrigger value="file">Загрузить файл</TabsTrigger>
              <TabsTrigger value="text">Добавить текст</TabsTrigger>
            </TabsList>
            <TabsContent value="file">
              <div
                className={`flex flex-col items-center rounded-lg border-2 border-dashed p-6 text-center ${isDragging ? "border-primary bg-muted/50" : ""}`}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
              >
                <FileUp className="text-muted-foreground mx-auto mb-2 h-8 w-8" />
                <p className="text-muted-foreground mb-2 text-sm">
                  Перетащите файлы сюда или нажмите для выбора
                </p>
                <Input
                  type="file"
                  className="hidden"
                  id="file-upload"
                  multiple
                  onChange={handleFileSelect}
                  accept={ACCEPTED_FILE_EXTENSIONS.join(",")}
                />
                <Label htmlFor="file-upload">
                  <Button variant="outline" className="mt-2" asChild>
                    <span>Выбрать файлы</span>
                  </Button>
                </Label>
              </div>
              {/* Staged Files Display */}
              {stagedFiles.length > 0 && (
                <div className="mt-4 space-y-2">
                  <h4 className="text-sm font-medium">Файлы для загрузки:</h4>
                  <ul className="space-y-1">
                    {stagedFiles.map((file, index) => (
                      <li
                        key={index}
                        className="flex items-center justify-between rounded-md border p-2 text-sm"
                      >
                        <span className="truncate pr-2">{file.name}</span>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-6 w-6 p-0"
                          onClick={() => removeStagedFile(index)}
                          aria-label={`Удалить ${file.name}`}
                        >
                          <X className="h-4 w-4" />
                        </Button>
                      </li>
                    ))}
                  </ul>
                  <Button
                    onClick={handleUploadStagedFiles}
                    disabled={!selectedCollection || isUploading}
                    className="mt-2 w-full"
                  >
                    <FileUp className="mr-2 h-4 w-4" />
                    {`Загрузить ${stagedFiles.length} файл(ов)`}
                  </Button>
                </div>
              )}
            </TabsContent>
            <TabsContent value="text">
              <div className="space-y-4">
                <Textarea
                  placeholder="Вставьте или введите текст здесь..."
                  className="min-h-[150px]"
                  value={textInput}
                  onChange={(e) => setTextInput(e.target.value)}
                />
                <Button
                  onClick={handleTextUpload}
                  disabled={!textInput.trim() || isUploading}
                >
                  <Plus className="mr-2 h-4 w-4" />
                  Добавить текстовый документ
                </Button>
              </div>
            </TabsContent>
          </Tabs>
        </div>

        {/* Document Table */}
        {selectedCollection && (
          <div className="rounded-md border">
            <DocumentsTable
              documents={currentDocuments}
              selectedCollection={selectedCollection}
              actionsDisabled={isUploading}
            />
          </div>
        )}

        {/* Pagination */}
        {filteredDocuments.length > itemsPerPage && (
          <Pagination className="mt-4">
            <PaginationContent>
              <PaginationItem>
                <PaginationPrevious
                  href="#"
                  onClick={(e) => {
                    e.preventDefault();
                    setCurrentPage(Math.max(1, currentPage - 1));
                  }}
                  aria-disabled={currentPage === 1}
                  className={
                    currentPage === 1
                      ? "text-muted-foreground pointer-events-none"
                      : undefined
                  }
                />
              </PaginationItem>
              {[...Array(totalPages)].map((_, page) => (
                <PaginationItem key={page + 1}>
                  <PaginationLink
                    href="#"
                    onClick={(e) => {
                      e.preventDefault();
                      setCurrentPage(page + 1);
                    }}
                    isActive={currentPage === page + 1}
                  >
                    {page + 1}
                  </PaginationLink>
                </PaginationItem>
              ))}
              <PaginationItem>
                <PaginationNext
                  href="#"
                  onClick={(e) => {
                    e.preventDefault();
                    setCurrentPage(Math.min(totalPages, currentPage + 1));
                  }}
                  aria-disabled={currentPage === totalPages}
                  className={
                    currentPage === totalPages
                      ? "text-muted-foreground pointer-events-none"
                      : undefined
                  }
                />
              </PaginationItem>
            </PaginationContent>
          </Pagination>
        )}
      </CardContent>
    </Card>
  );
}

export function DocumentsCardLoading() {
  return (
    <Card>
      <CardHeader>
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-6 w-48" />
      </CardHeader>
      <CardContent>
        <div className="mb-6 flex flex-col gap-6">
          <div className="flex items-center justify-start gap-2">
            <Skeleton className="h-6 w-22" />
            <Skeleton className="h-6 w-22" />
          </div>
          <Skeleton className="h-38 w-full" />
          <div className="flex flex-col gap-2">
            {Array.from({ length: 5 }).map((_, index) => (
              <Skeleton key={index} className="h-8 w-full" />
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
