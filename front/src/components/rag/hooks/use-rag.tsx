import { useState, Dispatch, SetStateAction, useCallback } from "react";
import { Document } from "@langchain/core/documents";
import { v4 as uuidv4 } from "uuid";
import { Collection, CollectionCreate } from "@/types/collection";
import { toast } from "sonner";
import { LANGCONNECT_API_URL, session } from "@/config.ts";
import { useSettings } from "@/components/Settings";

export const DEFAULT_COLLECTION_NAME = "default_collection";

export function getDefaultCollection(collections: Collection[]): Collection {
  return (
    collections.find((c) => c.name === DEFAULT_COLLECTION_NAME) ??
    collections[0]
  );
}

function getApiUrlOrThrow(): URL {
  if (!LANGCONNECT_API_URL) {
    throw new Error(
      "Failed to upload documents: API URL not configured. Please set NEXT_PUBLIC_RAG_API_URL",
    );
  }
  return new URL(
    LANGCONNECT_API_URL.replace("host.docker.internal", "localhost"),
  );
}

export function getCollectionName(name: string | undefined) {
  if (!name) return "";
  return name === DEFAULT_COLLECTION_NAME ? "Default" : name;
}

async function uploadDocuments(
  collectionId: string,
  files: File[],
  authorization: string,
  metadatas?: Record<string, any>[],
): Promise<any> {
  const url = `${getApiUrlOrThrow().href}collections/${encodeURIComponent(collectionId)}/documents`;

  const formData = new FormData();

  // Append files
  files.forEach((file) => {
    formData.append("files", file, file.name);
  });

  // Append metadatas if provided
  if (metadatas) {
    if (metadatas.length !== files.length) {
      throw new Error(
        `Number of metadata objects (${metadatas.length}) must match the number of files (${files.length}).`,
      );
    }
    // FastAPI expects the metadatas as a JSON *string* in the form data
    const metadatasJsonString = JSON.stringify(metadatas);
    formData.append("metadatas_json", metadatasJsonString);
  }

  try {
    const response = await fetch(url, {
      method: "POST",
      body: formData,
      headers: {
        Authorization: `Bearer ${authorization}`,
      },
    });

    if (!response.ok) {
      // Attempt to parse error details from the response body
      let errorDetail = `HTTP error! status: ${response.status}`;
      try {
        const errorJson = await response.json();
        errorDetail = errorJson.detail || JSON.stringify(errorJson);
      } catch (_) {
        // If parsing JSON fails, use the status text
        errorDetail = `${errorDetail} - ${response.statusText}`;
      }
      throw new Error(`Failed to upload documents: ${errorDetail}`);
    }

    return await response.json(); // Parse the successful JSON response
  } catch (error) {
    console.error("Error uploading documents:", error);
    throw error; // Re-throw the error for further handling
  }
}

// --- Type Definitions ---

// Return type for the combined hook
interface UseRagReturn {
  // Misc
  initialSearchExecuted: boolean;
  setInitialSearchExecuted: Dispatch<SetStateAction<boolean>>;
  // Initial load
  initialFetch: (accessToken: string) => Promise<void>;

  // Collection state and operations
  collections: Collection[];
  setCollections: Dispatch<SetStateAction<Collection[]>>;
  activeCollections: Record<string, boolean>;
  activateCollection: (collectionId: string) => void;
  deactivateCollection: (collectionId: string) => void;
  collectionsLoading: boolean;
  setCollectionsLoading: Dispatch<SetStateAction<boolean>>;
  getCollections: (accessToken?: string) => Promise<Collection[]>;
  createCollection: (
    name: string,
    metadata?: Record<string, any>,
    accessToken?: string,
  ) => Promise<Collection | undefined>;
  updateCollection: (
    collectionId: string,
    newName: string,
    metadata: Record<string, any>,
  ) => Promise<Collection | undefined>;
  deleteCollection: (collectionId: string) => Promise<string | undefined>;

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
    accessToken?: string,
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

  // --- Initial Fetch ---
  const initialFetch = useCallback(async (accessToken: string) => {
    setCollectionsLoading(true);
    setDocumentsLoading(true);
    let initCollections: Collection[] = [];

    try {
      initCollections = await getCollections(accessToken);
    } catch (e: any) {
      if (e.message.includes("Failed to fetch collections")) {
        // Database likely not initialized yet. Let's try this then re-fetch.
        await initializeDatabase(accessToken);
        initCollections = await getCollections(accessToken);
      }
    }

    if (!initCollections.length) {
      // No collections exist, return early
      setCollectionsLoading(false);
      setDocumentsLoading(false);
      setInitialSearchExecuted(true);
      return;
    }

    setCollections(initCollections);
    // Синхронизация активных коллекций со "входящими":
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

    const documents = await listDocuments(
      defaultCollection.uuid,
      {
        limit: 100,
      },
      accessToken,
    );
    setDocuments(documents);
    setDocumentsLoading(false);
  }, []);

  const initializeDatabase = useCallback(
    async (accessToken?: string) => {
      if (!session?.accessToken && !accessToken) {
        toast.error("Не удалось подключиться к LangConnect API", {
          richColors: true,
          description:
            "Не удалось получить список документов. Попробуйте ещё раз.",
        });
        return [];
      }

      const url = getApiUrlOrThrow();
      url.pathname += "admin/initialize-database";
      const response = await fetch(url.toString(), {
        method: "POST",
        headers: {
          Authorization: `Bearer ${accessToken || session?.accessToken}`,
        },
      });
      if (!response.ok) {
        throw new Error(
          `Не удалось инициализировать базу данных: ${response.statusText}`,
        );
      }
      const data = await response.json();
      return data;
    },
    [session],
  );

  // --- Document Operations ---

  const listDocuments = useCallback(
    async (
      collectionId: string,
      args?: { limit?: number; offset?: number },
      accessToken?: string,
    ): Promise<Document[]> => {
      if (!session?.accessToken && !accessToken) {
        toast.error("Не удалось подключиться к LangConnect API", {
          richColors: true,
          description:
            "Не удалось получить список документов. Попробуйте ещё раз.",
        });
        return [];
      }

      const url = getApiUrlOrThrow();
      url.pathname += `collections/${collectionId}/documents`;
      if (args?.limit) {
        url.searchParams.set("limit", args.limit.toString());
      }
      if (args?.offset) {
        url.searchParams.set("offset", args.offset.toString());
      }

      const response = await fetch(url.toString(), {
        headers: {
          Authorization: `Bearer ${accessToken || session?.accessToken}`,
        },
      });
      if (!response.ok) {
        throw new Error(`Failed to fetch documents: ${response.statusText}`);
      }
      const data = await response.json();
      return data;
    },
    [session],
  );

  const deleteDocument = useCallback(
    async (id: string) => {
      if (!session?.accessToken) {
        toast.error("Не удалось подключиться к LangConnect API", {
          richColors: true,
          description:
            "Не удалось получить удалить документ. Попробуйте ещё раз.",
        });
        return;
      }

      if (!selectedCollection) {
        throw new Error("No collection selected");
      }

      const url = getApiUrlOrThrow();
      url.pathname += `collections/${selectedCollection.uuid}/documents/${id}`;

      const response = await fetch(url.toString(), {
        method: "DELETE",
        headers: {
          Authorization: `Bearer ${session.accessToken}`,
        },
      });
      if (!response.ok) {
        throw new Error(`Failed to delete document: ${response.statusText}`);
      }

      setDocuments((prevDocs) =>
        prevDocs.filter((doc) => doc.metadata.file_id !== id),
      );
    },
    [selectedCollection, session],
  );

  const handleFileUpload = useCallback(
    async (files: FileList | null, collectionId: string) => {
      if (!session?.accessToken) {
        toast.error("Не удалось подключиться к LangConnect API", {
          richColors: true,
          description: "Не удалось загрузить файл(ы). Попробуйте ещё раз.",
        });
        return;
      }

      if (!files || files.length === 0) {
        console.warn("File upload skipped: No files selected.");
        return;
      }

      const newDocs: Document[] = Array.from(files).map((file) => {
        return new Document({
          id: uuidv4(),
          pageContent: `Содержимое ${file.name}`, // Placeholder: Real implementation needs file reading
          metadata: {
            name: file.name,
            collection: collectionId,
            size: `${(file.size / (1024 * 1024)).toFixed(1)} MB`,
            created_at: new Date().toISOString(),
          },
        });
      });

      await uploadDocuments(
        collectionId,
        Array.from(files),
        session.accessToken,
        newDocs.map((d) => d.metadata),
      );
      setDocuments((prevDocs) => [...prevDocs, ...newDocs]);
    },
    [session],
  );

  const handleTextUpload = useCallback(
    async (textInput: string, collectionId: string) => {
      if (!session?.accessToken) {
        toast.error("Не удалось подключиться к LangConnect API", {
          richColors: true,
          description:
            "Не удалось загрузить текстовый документ. Попробуйте ещё раз.",
        });
        return;
      }

      if (!textInput.trim()) {
        console.warn("Text upload skipped: Text is empty.");
        return;
      }
      const textBlob = new Blob([textInput], { type: "text/plain" });
      const fileName = `Текстовый документ ${new Date().toISOString().slice(0, 19).replace("T", " ")}.txt`;
      const textFile = new File([textBlob], fileName, { type: "text/plain" });
      const metadata = {
        name: fileName,
        collection: collectionId,
        size: `${(textInput.length / 1024).toFixed(1)} KB`,
        created_at: new Date().toISOString(),
      };
      await uploadDocuments(collectionId, [textFile], session.accessToken, [
        metadata,
      ]);
      setDocuments((prevDocs) => [
        ...prevDocs,
        new Document({
          id: uuidv4(),
          pageContent: textInput,
          metadata,
        }),
      ]);
    },
    [session],
  );

  // --- Collection Operations ---

  const getCollections = useCallback(
    async (accessToken?: string): Promise<Collection[]> => {
      if (!session?.accessToken && !accessToken) {
        toast.error("Не удалось подключиться к LangConnect API", {
          richColors: true,
          description: "Не удалось получить коллекции. Попробуйте ещё раз.",
        });
        return [];
      }

      const url = getApiUrlOrThrow();
      url.pathname += "collections";

      const response = await fetch(url.toString(), {
        headers: {
          Authorization: `Bearer ${accessToken || session?.accessToken}`,
        },
      });
      if (!response.ok) {
        throw new Error(`Failed to fetch collections: ${response.statusText}`);
      }
      const data = await response.json();
      return data;
    },
    [session],
  );

  const createCollection = useCallback(
    async (
      name: string,
      metadata: Record<string, any> = {},
      accessToken?: string,
    ): Promise<Collection | undefined> => {
      if (!session?.accessToken && !accessToken) {
        toast.error("Не удалось подключиться к LangConnect API", {
          richColors: true,
          description: "Не удалось создать коллекцию. Попробуйте ещё раз.",
        });
        return;
      }

      const url = getApiUrlOrThrow();
      url.pathname += "collections";

      const trimmedName = name.trim();
      if (!trimmedName) {
        console.error("Collection name cannot be empty.");
        return undefined;
      }
      const nameExists = collections.some(
        (c) => c.name.toLowerCase() === trimmedName.toLowerCase(),
      );
      if (nameExists) {
        console.warn(`Collection with name "${trimmedName}" already exists.`);
        return undefined;
      }

      const newCollection: CollectionCreate = {
        name: trimmedName,
        metadata,
      };
      const response = await fetch(url.toString(), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${accessToken || session?.accessToken}`,
        },
        body: JSON.stringify(newCollection),
      });
      if (!response.ok) {
        console.error(`Failed to create collection: ${response.statusText}`);
        return undefined;
      }
      const data = await response.json();
      setCollections((prevCollections) => [...prevCollections, data]);
      // новая коллекция по умолчанию активна
      setSettings((prev) => ({
        ...prev,
        activeCollections: {
          ...(prev.activeCollections || {}),
          [data.uuid]: true,
        },
      }));
      return data;
    },
    [collections, session, setSettings],
  );

  const updateCollection = useCallback(
    async (
      collectionId: string,
      newName: string,
      metadata: Record<string, any>,
    ): Promise<Collection | undefined> => {
      if (!session?.accessToken) {
        toast.error("Не удалось подключиться к LangConnect API", {
          richColors: true,
          description: "Не удалось обновить коллекцию. Попробуйте ещё раз.",
        });
        return;
      }

      // Find the collection to update
      const collectionToUpdate = collections.find(
        (c) => c.uuid === collectionId,
      );

      if (!collectionToUpdate) {
        toast.error(`Коллекция с ID "${collectionId}" не найдена.`, {
          richColors: true,
        });
        return undefined;
      }

      const trimmedNewName = newName.trim();
      if (!trimmedNewName) {
        toast.error("Название коллекции не может быть пустым.", {
          richColors: true,
        });
        return undefined;
      }

      // Check if the new name already exists (only if name is changing)
      const nameExists = collections.some(
        (c) =>
          c.name.toLowerCase() === trimmedNewName.toLowerCase() &&
          c.name !== collectionToUpdate.name,
      );
      if (nameExists) {
        toast.warning(
          `Коллекция с именем "${trimmedNewName}" уже существует.`,
          {
            richColors: true,
          },
        );
        return undefined;
      }

      const url = getApiUrlOrThrow();
      url.pathname += `collections/${collectionId}`;

      const updateData = {
        name: trimmedNewName,
        metadata: metadata,
      };

      const response = await fetch(url.toString(), {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${session.accessToken}`,
        },
        body: JSON.stringify(updateData),
      });

      if (!response.ok) {
        toast.error(`Не удалось обновить коллекцию: ${response.statusText}`, {
          richColors: true,
        });
        return undefined;
      }

      const updatedCollection = await response.json();

      // Update the collections state
      setCollections((prevCollections) =>
        prevCollections.map((collection) =>
          collection.uuid === collectionId ? updatedCollection : collection,
        ),
      );

      // Update selected collection if it was the one that got updated
      if (selectedCollection && selectedCollection.uuid === collectionId) {
        setSelectedCollection(updatedCollection);
      }

      return updatedCollection;
    },
    [collections, selectedCollection, session],
  );

  const deleteCollection = useCallback(
    async (collectionId: string): Promise<string | undefined> => {
      if (!session?.accessToken) {
        toast.error("Не удалось подключиться к LangConnect API", {
          richColors: true,
          description: "Не удалось удалить коллекцию. Попробуйте ещё раз.",
        });
        return;
      }

      const collectionToDelete = collections.find(
        (c) => c.uuid === collectionId,
      );

      if (!collectionToDelete) {
        return;
      }

      const url = getApiUrlOrThrow();
      url.pathname += `collections/${collectionId}`;

      const response = await fetch(url.toString(), {
        method: "DELETE",
        headers: {
          Authorization: `Bearer ${session.accessToken}`,
        },
      });

      if (!response.ok) {
        console.error(`Failed to delete collection: ${response.statusText}`);
        return undefined;
      }

      // Delete the collection itself
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
    [collections, session, setSettings],
  );

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
