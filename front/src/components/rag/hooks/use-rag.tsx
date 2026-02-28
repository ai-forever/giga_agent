import { useState, Dispatch, SetStateAction, useCallback } from "react";
import { Document } from "@langchain/core/documents";
import { Collection, CollectionCreate } from "@/types/collection";
import { toast } from "sonner";
import { useSettings } from "@/components/Settings";
import { API_AGENT_PREFIX } from "@/config.ts";
import { apiClient, ApiError } from "@/lib/api-client";

export const DEFAULT_COLLECTION_NAME = "default_collection";

export function getDefaultCollection(collections: Collection[]): Collection {
  return (
    collections.find((c) => c.name === DEFAULT_COLLECTION_NAME) ??
    collections[0]
  );
}

export function getCollectionName(name: string | undefined) {
  if (!name) return "";
  return name === DEFAULT_COLLECTION_NAME ? "Default" : name;
}

type RagDocumentResponse = {
  id: string;
  collection_id: string;
  content?: string | null;
  metadata?: Record<string, any> | null;
  created_at?: string | null;
  updated_at?: string | null;
};

function mapApiDocumentToLangchain(doc: RagDocumentResponse): Document {
  const metadata: Record<string, any> = { ...(doc.metadata || {}) };

  // UI ожидает эти поля (см. DocumentsCard / DocumentsTable)
  metadata.file_id = metadata.file_id ?? doc.id;
  metadata.name = metadata.name ?? metadata.original_name ?? "document";
  metadata.created_at = metadata.created_at ?? doc.created_at ?? null;
  metadata.collection = metadata.collection ?? doc.collection_id;

  return new Document({
    id: doc.id,
    pageContent: doc.content ?? "",
    metadata,
  });
}

// --- Type Definitions ---

// Return type for the combined hook
interface UseRagReturn {
  // Misc
  initialSearchExecuted: boolean;
  setInitialSearchExecuted: Dispatch<SetStateAction<boolean>>;
  // Initial load
  initialFetch: () => Promise<void>;

  // Collection state and operations
  collections: Collection[];
  setCollections: Dispatch<SetStateAction<Collection[]>>;
  activeCollections: Record<string, boolean>;
  activateCollection: (collectionId: string) => void;
  deactivateCollection: (collectionId: string) => void;
  collectionsLoading: boolean;
  setCollectionsLoading: Dispatch<SetStateAction<boolean>>;
  getCollections: () => Promise<Collection[]>;
  createCollection: (
    name: string,
    metadata?: Record<string, any>,
  ) => Promise<Collection | undefined>;
  updateCollection: (
    collectionId: string,
    newName: string,
    metadata: Record<string, any>,
  ) => Promise<Collection | undefined>;
  deleteCollection: (collectionId: string) => Promise<void>;

  // Selected collection
  selectedCollection: Collection | undefined;
  setSelectedCollection: Dispatch<SetStateAction<Collection | undefined>>;

  // Document state and operations
  documents: Document[];
  setDocuments: Dispatch<SetStateAction<Document[]>>;
  documentsLoading: boolean;
  setDocumentsLoading: Dispatch<SetStateAction<boolean>>;
  listDocuments: (
    collectionId: string,
    args?: { limit?: number; offset?: number },
  ) => Promise<Document[]>;
  deleteDocument: (id: string) => Promise<void>;
  handleFileUpload: (
    files: FileList | null,
    collectionId: string,
  ) => Promise<void>;
  handleTextUpload: (textInput: string, collectionId: string) => Promise<void>;
}

/**
 * Custom hook for managing RAG collections and documents.
 * Combines the logic of useCollections and useDocuments.
 */
export function useRag(): UseRagReturn {
  // --- State ---
  const [collections, setCollections] = useState<Collection[]>([]);
  const [collectionsLoading, setCollectionsLoading] = useState(false);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [documentsLoading, setDocumentsLoading] = useState(false);
  const [selectedCollection, setSelectedCollection] = useState<
    Collection | undefined
  >(undefined);
  const [initialSearchExecuted, setInitialSearchExecuted] = useState(false);
  const { settings, setSettings } = useSettings();
  const activeCollections: Record<string, boolean> =
    settings.activeCollections || {};

  const activateCollection = useCallback(
    (collectionId: string) => {
      setSettings((prev) => ({
        ...prev,
        activeCollections: {
          ...(prev.activeCollections || {}),
          [collectionId]: true,
        },
      }));
    },
    [setSettings],
  );

  const deactivateCollection = useCallback(
    (collectionId: string) => {
      setSettings((prev) => ({
        ...prev,
        activeCollections: {
          ...(prev.activeCollections || {}),
          [collectionId]: false,
        },
      }));
    },
    [setSettings],
  );

  const getCollections = useCallback(async (): Promise<Collection[]> => {
    const data = await apiClient.get<Collection[]>(
      `${API_AGENT_PREFIX}/rag/collections`,
    );
    return Array.isArray(data) ? data : [];
  }, []);

  const createCollection = useCallback(
    async (
      name: string,
      metadata: Record<string, any> = {},
    ): Promise<Collection | undefined> => {
      const trimmedName = name.trim();
      if (!trimmedName) return undefined;

      const nameExists = collections.some(
        (c) => c.name.toLowerCase() === trimmedName.toLowerCase(),
      );
      if (nameExists) {
        return undefined;
      }

      const newCollection: CollectionCreate = {
        name: trimmedName,
        metadata,
      };

      try {
        const created = await apiClient.post<Collection>(
          `${API_AGENT_PREFIX}/rag/collections`,
          newCollection,
          { showError: false },
        );
        setCollections((prevCollections) => [...prevCollections, created]);
        // новая папка по умолчанию активна
        setSettings((prev) => ({
          ...prev,
          activeCollections: {
            ...(prev.activeCollections || {}),
            [created.uuid]: true,
          },
        }));
        return created;
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) {
          return undefined;
        }
        throw e;
      }
    },
    [collections, setSettings],
  );

  const updateCollection = useCallback(
    async (
      collectionId: string,
      newName: string,
      metadata: Record<string, any>,
    ): Promise<Collection | undefined> => {
      const collectionToUpdate = collections.find(
        (c) => c.uuid === collectionId,
      );
      if (!collectionToUpdate) {
        toast.error(`Папка с ID "${collectionId}" не найдена.`, {
          richColors: true,
        });
        return undefined;
      }

      const trimmedNewName = newName.trim();
      if (!trimmedNewName) {
        toast.error("Название папки не может быть пустым.", {
          richColors: true,
        });
        return undefined;
      }

      const nameExists = collections.some(
        (c) =>
          c.name.toLowerCase() === trimmedNewName.toLowerCase() &&
          c.name !== collectionToUpdate.name,
      );
      if (nameExists) {
        toast.warning(`Папка с именем "${trimmedNewName}" уже существует.`, {
          richColors: true,
        });
        return undefined;
      }

      const updateData = {
        name: trimmedNewName,
        metadata,
      };

      const updated = await apiClient.patch<Collection>(
        `${API_AGENT_PREFIX}/rag/collections/${collectionId}`,
        updateData,
      );

      setCollections((prevCollections) =>
        prevCollections.map((collection) =>
          collection.uuid === collectionId ? updated : collection,
        ),
      );

      if (selectedCollection && selectedCollection.uuid === collectionId) {
        setSelectedCollection(updated);
      }

      return updated;
    },
    [collections, selectedCollection],
  );

  const deleteCollection = useCallback(
    async (collectionId: string): Promise<void> => {
      const collectionToDelete = collections.find(
        (c) => c.uuid === collectionId,
      );
      if (!collectionToDelete) return;

      await apiClient.delete(
        `${API_AGENT_PREFIX}/rag/collections/${collectionId}`,
      );

      setCollections((prevCollections) =>
        prevCollections.filter(
          (collection) => collection.uuid !== collectionId,
        ),
      );
      // удалить из активных
      setSettings((prev) => {
        const { [collectionId]: _removed, ...rest } =
          prev.activeCollections || {};
        return { ...prev, activeCollections: rest };
      });
    },
    [collections, setSettings],
  );

  const listDocuments = useCallback(
    async (
      collectionId: string,
      args?: { limit?: number; offset?: number },
    ): Promise<Document[]> => {
      const searchParams = new URLSearchParams();
      if (args?.limit) searchParams.set("limit", String(args.limit));
      if (args?.offset) searchParams.set("offset", String(args.offset));
      const qs = searchParams.toString();

      const data = await apiClient.get<RagDocumentResponse[]>(
        `${API_AGENT_PREFIX}/rag/collections/${encodeURIComponent(collectionId)}/documents${qs ? `?${qs}` : ""}`,
      );
      const rows = Array.isArray(data) ? data : [];
      return rows.map(mapApiDocumentToLangchain);
    },
    [],
  );

  // --- Initial Fetch ---
  const initialFetch = useCallback(async () => {
    setCollectionsLoading(true);
    setDocumentsLoading(true);
    let initCollections: Collection[] = [];

    try {
      initCollections = await getCollections();
    } catch {
      // handled globally
      initCollections = [];
    }

    if (!initCollections.length) {
      // No collections exist, return early
      setCollectionsLoading(false);
      setDocumentsLoading(false);
      setInitialSearchExecuted(true);
      return;
    }

    setCollections(initCollections);
    // Синхронизация активных папок со "входящими":
    // - сохраняем статусы существующих, которые остались во входящих
    // - удаляем отсутствующие
    // - добавляем новые как enabled=true
    setSettings((prev) => {
      const prevMap = prev.activeCollections || {};
      const next: Record<string, boolean> = {};
      const incomingIds = new Set(initCollections.map((c) => c.uuid));
      Object.entries(prevMap).forEach(([id, enabled]) => {
        if (incomingIds.has(id)) next[id] = enabled as boolean;
      });
      initCollections.forEach((c) => {
        if (!(c.uuid in next)) next[c.uuid] = true;
      });
      return { ...prev, activeCollections: next };
    });
    const defaultCollection = initCollections[0];
    setSelectedCollection(defaultCollection);

    setInitialSearchExecuted(true);
    setCollectionsLoading(false);

    const documents = await listDocuments(defaultCollection.uuid, {
      limit: 100,
    });
    setDocuments(documents);
    setDocumentsLoading(false);
  }, [getCollections, listDocuments, setSettings]);

  // --- Document Operations ---

  const deleteDocument = useCallback(
    async (id: string) => {
      if (!selectedCollection) {
        throw new Error("No collection selected");
      }

      await apiClient.delete(
        `${API_AGENT_PREFIX}/rag/collections/${selectedCollection.uuid}/documents/${encodeURIComponent(id)}`,
      );

      setDocuments((prevDocs) =>
        prevDocs.filter((doc) => doc.metadata.file_id !== id),
      );
    },
    [selectedCollection],
  );

  const handleFileUpload = useCallback(
    async (files: FileList | null, collectionId: string) => {
      if (!files || files.length === 0) {
        console.warn("File upload skipped: No files selected.");
        return;
      }

      const filesArray = Array.from(files);
      const metadatas = filesArray.map((file) => ({
        name: file.name,
        size: file.size,
        created_at: new Date().toISOString(),
      }));

      const formData = new FormData();
      filesArray.forEach((file) => {
        formData.append("files", file, file.name);
      });
      formData.append("metadatas_json", JSON.stringify(metadatas));

      await apiClient.post(
        `${API_AGENT_PREFIX}/rag/collections/${encodeURIComponent(collectionId)}/documents`,
        formData,
      );

      const nextDocs = await listDocuments(collectionId, { limit: 100 });
      setDocuments(nextDocs);
    },
    [listDocuments],
  );

  const handleTextUpload = useCallback(
    async (textInput: string, collectionId: string) => {
      if (!textInput.trim()) {
        console.warn("Text upload skipped: Text is empty.");
        return;
      }
      const textBlob = new Blob([textInput], { type: "text/plain" });
      const fileName = `Текстовый документ ${new Date().toISOString().slice(0, 19).replace("T", " ")}.txt`;
      const textFile = new File([textBlob], fileName, { type: "text/plain" });
      const metadata = {
        name: fileName,
        size: textInput.length,
        created_at: new Date().toISOString(),
      };

      const formData = new FormData();
      formData.append("files", textFile, textFile.name);
      formData.append("metadatas_json", JSON.stringify([metadata]));

      await apiClient.post(
        `${API_AGENT_PREFIX}/rag/collections/${encodeURIComponent(collectionId)}/documents`,
        formData,
      );

      const nextDocs = await listDocuments(collectionId, { limit: 100 });
      setDocuments(nextDocs);
    },
    [listDocuments],
  );

  // --- Collection Operations ---

  // --- Return combined state and functions ---
  return {
    // Misc
    initialSearchExecuted,
    setInitialSearchExecuted,
    initialFetch,

    // Collections
    collections,
    setCollections,
    activeCollections,
    activateCollection,
    deactivateCollection,
    collectionsLoading,
    setCollectionsLoading,
    getCollections,
    createCollection,
    updateCollection,
    deleteCollection,

    selectedCollection,
    setSelectedCollection,

    // Documents
    documents,
    setDocuments,
    documentsLoading,
    setDocumentsLoading,
    listDocuments,
    deleteDocument,
    handleFileUpload,
    handleTextUpload,
  };
}
