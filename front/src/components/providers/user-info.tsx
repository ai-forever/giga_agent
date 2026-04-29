import React, {
  createContext,
  useContext,
  PropsWithChildren,
  useState,
  useCallback,
} from "react";
import McpServerModal, { MCPTool } from "@/components/mcp/mcp-modal.tsx";
import ContextModal from "@/components/modals/context-modal.tsx";

const ENABLED_MODULES_KEY = "giga_agent_enabled_modules";

const readEnabledModules = (): Record<string, boolean> => {
  try {
    const raw = localStorage.getItem(ENABLED_MODULES_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed))
      return {};
    const result: Record<string, boolean> = {};
    for (const [k, v] of Object.entries(parsed)) {
      if (typeof v === "boolean") result[k] = v;
    }
    return result;
  } catch {
    return {};
  }
};

type UserInfoContextType = {
  mcpTools: MCPTool[];
  setMcpTools: React.Dispatch<React.SetStateAction<MCPTool[]>>;
  openMcpModal: () => void;
  closeMcpModal: () => void;
  openContextModal: () => void;
  closeContextModal: () => void;
  enabledModules: Record<string, boolean>;
  toggleModule: (moduleId: string, enabled: boolean) => void;
};

const UserInfoContext = createContext<UserInfoContextType | null>(null);

export const UserInfoProvider: React.FC<PropsWithChildren> = ({ children }) => {
  const [mcpTools, setMcpTools] = useState<MCPTool[]>([]);
  const [mcpModalOpen, setMcpModalOpen] = useState(false);
  const [contextModalOpen, setContextModalOpen] = useState(false);
  const [enabledModules, setEnabledModules] = useState<
    Record<string, boolean>
  >(readEnabledModules);

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

  const toggleModule = useCallback(
    (moduleId: string, enabled: boolean) => {
      setEnabledModules((prev) => {
        const next = { ...prev, [moduleId]: enabled };
        try {
          localStorage.setItem(ENABLED_MODULES_KEY, JSON.stringify(next));
        } catch {
          /* storage unavailable */
        }
        return next;
      });
    },
    [setEnabledModules],
  );

  return (
    <UserInfoContext.Provider
      value={{
        mcpTools,
        setMcpTools,
        openMcpModal,
        closeMcpModal,
        openContextModal,
        closeContextModal,
        enabledModules,
        toggleModule,
      }}
    >
      {children}
      <McpServerModal
        isOpen={mcpModalOpen}
        onClose={closeMcpModal}
        onToolsUpdate={setMcpTools}
      />
      <ContextModal isOpen={contextModalOpen} onClose={closeContextModal} />
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
