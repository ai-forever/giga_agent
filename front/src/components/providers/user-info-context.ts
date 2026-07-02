import React, { createContext, useContext } from "react";
import { type MCPTool } from "@/components/mcp/mcp-modal.tsx";
import { type ConnectorsTab } from "@/components/mcp/connectors/connectors-modal.tsx";
import { type UseConnectorsResult } from "@/components/mcp/connectors/use-connectors.ts";

export interface ModuleInfo {
  id: string;
  label: string;
  description: string;
  icon: string;
}

export type UserInfoContextType = {
  mcpTools: MCPTool[];
  setMcpTools: React.Dispatch<React.SetStateAction<MCPTool[]>>;
  connectors: UseConnectorsResult;
  openConnectors: (tab?: ConnectorsTab) => void;
  openContextModal: () => void;
  closeContextModal: () => void;
  enabledModules: Record<string, boolean>;
  toggleModule: (moduleId: string, enabled: boolean) => Promise<void>;
  setModulesState: (updates: Record<string, boolean>) => Promise<void>;
  availableModules: ModuleInfo[];
  refreshModules: () => void;
};

export const UserInfoContext = createContext<UserInfoContextType | null>(null);

export const useUserInfo = () => {
  const context = useContext(UserInfoContext);
  if (context === null) {
    throw new Error("useUserInfo must be used within a UserInfoProvider");
  }
  return context;
};
