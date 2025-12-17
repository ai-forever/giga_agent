"use client";

import type React from "react";
import { useState } from "react";

import { useRagContext } from "./providers/RAG";
import EmptyCollectionsState from "@/components/rag/empty-collections.tsx";
import {
  CollectionsCard,
  CollectionsCardLoading,
} from "@/components/rag/collections-card.tsx";
import {
  DocumentsCard,
  DocumentsCardLoading,
} from "@/components/rag/documents-card";

export default function RAGInterface() {
  const {
    selectedCollection,
    setSelectedCollection,
    collections,
    initialSearchExecuted,
  } = useRagContext();
  const [currentPage, setCurrentPage] = useState(1);

  if (initialSearchExecuted && !collections.length) {
    return <EmptyCollectionsState />;
  }

  return (
    <div className="container mx-auto p-5">
      <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
        {/* Collections Section */}
        <div className="md:col-span-1">
          {initialSearchExecuted ? (
            <CollectionsCard
              collections={collections}
              selectedCollection={selectedCollection}
              setSelectedCollection={setSelectedCollection}
              setCurrentPage={setCurrentPage}
            />
          ) : (
            <CollectionsCardLoading />
          )}
        </div>

        {/* Documents Section */}
        <div className="md:col-span-2">
          {initialSearchExecuted ? (
            <DocumentsCard
              selectedCollection={selectedCollection}
              currentPage={currentPage}
              setCurrentPage={setCurrentPage}
            />
          ) : (
            <DocumentsCardLoading />
          )}
        </div>
      </div>
    </div>
  );
}
