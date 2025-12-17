"use client";

import type React from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { Collection } from "@/types/collection";
import { useState } from "react";
import { CollectionsList } from "./collections-list";
import { CreateCollectionDialog } from "./create-collection-dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { useRagContext } from "@/components/rag/providers/RAG.tsx";
import { toast } from "sonner";

interface CollectionsCardProps {
  collections: Collection[];
  selectedCollection: Collection | undefined;
  setSelectedCollection: React.Dispatch<
    React.SetStateAction<Collection | undefined>
  >;
  setCurrentPage: React.Dispatch<React.SetStateAction<number>>;
}

export function CollectionsCard({
  collections,
  selectedCollection,
  setSelectedCollection,
  setCurrentPage,
}: CollectionsCardProps) {
  const {
    createCollection,
    deleteCollection,
    listDocuments,
    setDocuments,
    updateCollection,
  } = useRagContext();

  const [open, setOpen] = useState(false);

  // State for pagination
  const [collectionsCurrentPage, setCollectionsCurrentPage] = useState(1);
  const collectionsItemsPerPage = 5;

  // Handle creating a new collection (uses hook)
  const handleCreateCollection = async (name: string, description: string) => {
    const loadingToast = toast.loading("Создание коллекции", {
      richColors: true,
    });
    const success = await createCollection(name, {
      description,
    });
    toast.dismiss(loadingToast);
    if (success) {
      setOpen(false);
      toast.success("Коллекция успешно создана", { richColors: true });
    } else {
      toast.warning(
        `Не удалось создать коллекцию с именем '${name}' (вероятно, уже существует).`,
        {
          duration: 5000,
          richColors: true,
        },
      );
    }
  };

  // Handle deleting a collection (uses collection hook and document hook)
  const handleDeleteCollection = async (id: string) => {
    const loadingToast = toast.loading("Удаление коллекции", {
      richColors: true,
    });
    await deleteCollection(id);
    toast.dismiss(loadingToast);
    toast.success("Коллекция успешно удалена", { richColors: true });
    if (selectedCollection?.uuid === id) {
      const newSelectedCollection = collections.find((c) => c.uuid !== id);
      if (!newSelectedCollection) {
        toast.error("Коллекций не осталось.", { richColors: true });
        return;
      }
      setSelectedCollection(newSelectedCollection);
      setCurrentPage(1); // Reset document page
      const docs = await listDocuments(newSelectedCollection.uuid);
      setDocuments(docs);
    }
  };

  const handleUpdateCollection = async (
    id: string,
    name: string,
    metadata: Record<string, any>,
  ) => {
    const loadingToast = toast.loading("Обновление коллекции", {
      richColors: true,
    });
    await updateCollection(id, name, metadata);
    toast.dismiss(loadingToast);
    toast.success("Коллекция успешно обновлена", { richColors: true });
  };

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>Коллекции</CardTitle>
        <CreateCollectionDialog
          open={open}
          onOpenChange={setOpen}
          onSubmit={handleCreateCollection}
        />
      </CardHeader>
      <CardContent>
        <CollectionsList
          collections={collections}
          selectedCollection={selectedCollection}
          onSelect={async (id) => {
            if (selectedCollection?.uuid === id) {
              return;
            }
            setSelectedCollection(collections.find((c) => c.uuid === id));
            setCurrentPage(1); // Reset page when collection changes
            setCollectionsCurrentPage(1);
            const documents = await listDocuments(id);
            setDocuments(documents);
          }}
          onDelete={(id) => handleDeleteCollection(id)}
          onEdit={handleUpdateCollection}
          currentPage={collectionsCurrentPage}
          itemsPerPage={collectionsItemsPerPage}
          totalCollections={collections.length}
          onPageChange={setCollectionsCurrentPage}
        />
      </CardContent>
    </Card>
  );
}

export function CollectionsCardLoading() {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <Skeleton className="h-8 w-24" />
        <Skeleton className="size-8" />
      </CardHeader>
      <CardContent>
        <div className="flex flex-col gap-2">
          {Array.from({ length: 5 }).map((_, index) => (
            <Skeleton key={index} className="h-8 w-full" />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
