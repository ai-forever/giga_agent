import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

export type SelectedAttachmentsMap = Record<string, { alt?: string }>;

export interface SelectedAttachmentsContextValue {
  selected: SelectedAttachmentsMap;
  toggle: (id: string, alt?: string) => void;
  isSelected: (id: string) => boolean;
  clear: () => void;
  setSelectedAttachments: (value: SelectedAttachmentsMap) => void;
}

const SelectedAttachmentsContext = createContext<
  SelectedAttachmentsContextValue | undefined
>(undefined);

export const useSelectedAttachments = (): SelectedAttachmentsContextValue => {
  const ctx = useContext(SelectedAttachmentsContext);
  if (!ctx) {
    throw new Error(
      "useSelectedAttachments must be used within SelectedAttachmentsProvider",
    );
  }
  return ctx;
};

interface SelectedAttachmentsProviderProps {
  children: React.ReactNode;
}

export const SelectedAttachmentsProvider: React.FC<
  SelectedAttachmentsProviderProps
> = ({ children }) => {
  const [selectedAttachments, setSelectedAttachments] =
    useState<SelectedAttachmentsMap>({});

  const toggle = useCallback((id: string, alt?: string) => {
    setSelectedAttachments((prev) => {
      if (id in prev) {
        const { [id]: _removed, ...rest } = prev;
        return rest;
      }
      return { ...prev, [id]: { alt } };
    });
  }, []);

  const isSelected = useCallback(
    (id: string) => {
      return id in selectedAttachments;
    },
    [selectedAttachments],
  );

  const clear = useCallback(() => setSelectedAttachments({}), []);

  const value = useMemo<SelectedAttachmentsContextValue>(
    () => ({
      selected: selectedAttachments,
      toggle,
      isSelected,
      clear,
      setSelectedAttachments,
    }),
    [selectedAttachments, toggle, isSelected, clear, setSelectedAttachments],
  );

  return (
    <SelectedAttachmentsContext.Provider value={value}>
      {children}
    </SelectedAttachmentsContext.Provider>
  );
};

export default SelectedAttachmentsContext;
