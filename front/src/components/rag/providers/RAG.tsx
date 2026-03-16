import React, { createContext, useContext, PropsWithChildren } from "react";
import { useRag } from "../hooks/use-rag";
import { useEffect } from "react";
import { useAuth } from "@/components/providers/auth";

type RagContextType = ReturnType<typeof useRag>;

const RagContext = createContext<RagContextType | null>(null);

export const RagProvider: React.FC<PropsWithChildren> = ({ children }) => {
  const ragState = useRag();
  const { token } = useAuth();

  useEffect(() => {
    if (
      ragState.collections.length > 0 ||
      ragState.initialSearchExecuted ||
      !token
    ) {
      return;
    }
    ragState.initialFetch();
  }, [
    ragState.collections.length,
    ragState.initialSearchExecuted,
    ragState.initialFetch,
    token,
  ]);

  return <RagContext.Provider value={ragState}>{children}</RagContext.Provider>;
};

export const useRagContext = () => {
  const context = useContext(RagContext);
  if (context === null) {
    throw new Error("useRagContext must be used within a RagProvider");
  }
  return context;
};
