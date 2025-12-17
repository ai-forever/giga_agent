import React, {
  createContext,
  useContext,
  PropsWithChildren,
  useState,
  useCallback,
} from "react";
import McpServerModal, { MCPTool } from "@/components/mcp/mcp-modal.tsx";
import ContextModal from "@/components/modals/context-modal.tsx";
import CollectionsModal from "@/components/modals/collections-modal.tsx";

type UserInfoContextType = {
  mcpTools: MCPTool[];
  setMcpTools: React.Dispatch<React.SetStateAction<MCPTool[]>>;
  openMcpModal: () => void;
  closeMcpModal: () => void;
  openContextModal: () => void;
  closeContextModal: () => void;
  openCollectionsModal: () => void;
  closeCollectionsModal: () => void;
};

const UserInfoContext = createContext<UserInfoContextType | null>(null);

export const UserInfoProvider: React.FC<PropsWithChildren> = ({ children }) => {
  const [mcpTools, setMcpTools] = useState<MCPTool[]>([]);
  const [mcpModalOpen, setMcpModalOpen] = useState(false);
  const [contextModalOpen, setContextModalOpen] = useState(false);
  const [collectionsModalOpen, setCollectionModalOpen] = useState(false);

  const openMcpModal = useCallback(() => {
    setMcpModalOpen(true);
  }, [setMcpModalOpen]);

  const closeMcpModal = useCallback(() => {
    setMcpModalOpen(false);
  }, [setMcpModalOpen]);

  const openContextModal = useCallback(() => {
    setContextModalOpen(true);
  }, [setContextModalOpen]);

  const closeContextModal = useCallback(() => {
    setContextModalOpen(false);
  }, [setContextModalOpen]);

  const openCollectionsModal = useCallback(() => {
    setCollectionModalOpen(true);
  }, [setCollectionModalOpen]);

  const closeCollectionsModal = useCallback(() => {
    setCollectionModalOpen(false);
  }, [setCollectionModalOpen]);

  return (
    <UserInfoContext.Provider
      value={{
        mcpTools,
        setMcpTools,
        openMcpModal,
        closeMcpModal,
        openContextModal,
        closeContextModal,
        openCollectionsModal,
        closeCollectionsModal,
      }}
    >
      {children}
      <McpServerModal
        isOpen={mcpModalOpen}
        onClose={closeMcpModal}
        onToolsUpdate={setMcpTools}
      />
      <ContextModal isOpen={contextModalOpen} onClose={closeContextModal} />
      <CollectionsModal
        isOpen={collectionsModalOpen}
        onClose={closeCollectionsModal}
      />
    </UserInfoContext.Provider>
  );
};

export const useUserInfo = () => {
  const context = useContext(UserInfoContext);
  if (context === null) {
    throw new Error("useUserInfo must be used within a UserInfoProvider");
  }
  return context;
};
