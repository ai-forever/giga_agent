import React, {
  createContext,
  PropsWithChildren,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { type MCPTool } from "@/components/mcp/mcp-modal.tsx";
import ContextModal from "@/components/modals/context-modal.tsx";
import ConnectorsDirectoryModal from "@/components/mcp/connectors/directory-modal.tsx";
import ConnectorsManageModal from "@/components/mcp/connectors/manage-modal.tsx";
import {
  useConnectors,
  type UseConnectorsResult,
} from "@/components/mcp/connectors/use-connectors.ts";
import { API_AGENT_PREFIX } from "@/config.ts";
import { useAuth } from "@/components/providers/auth.tsx";

export interface ModuleInfo {
  id: string;
  label: string;
  description: string;
  icon: string;
}

const readDisabledFromUser = (user: unknown): string[] => {
  const settings = (user as { settings?: unknown } | null | undefined)
    ?.settings;
  if (!settings || typeof settings !== "object") return [];
  const raw = (settings as Record<string, unknown>).disabledModules;
  if (!Array.isArray(raw)) return [];
  return raw.filter((x): x is string => typeof x === "string");
};

type UserInfoContextType = {
  mcpTools: MCPTool[];
  setMcpTools: React.Dispatch<React.SetStateAction<MCPTool[]>>;
  connectors: UseConnectorsResult;
  openConnectorsDirectory: () => void;
  openConnectorsManage: () => void;
  openContextModal: () => void;
  closeContextModal: () => void;
  enabledModules: Record<string, boolean>;
  toggleModule: (moduleId: string, enabled: boolean) => Promise<void>;
  setModulesState: (updates: Record<string, boolean>) => Promise<void>;
  availableModules: ModuleInfo[];
  refreshModules: () => void;
};

const UserInfoContext = createContext<UserInfoContextType | null>(null);

export const UserInfoProvider: React.FC<PropsWithChildren> = ({ children }) => {
  const [mcpTools, setMcpTools] = useState<MCPTool[]>([]);
  const connectors = useConnectors();
  const [directoryOpen, setDirectoryOpen] = useState(false);
  const [manageOpen, setManageOpen] = useState(false);
  const [contextModalOpen, setContextModalOpen] = useState(false);
  const [availableModules, setAvailableModules] = useState<ModuleInfo[]>([]);
  const { token, user, refreshUser } = useAuth();

  // disabledModules — единый источник правды из user.settings.
  // Локально храним для optimistic-апдейтов; синхронизируем при смене user.
  const disabledFromUser = useMemo(() => readDisabledFromUser(user), [user]);
  const [localDisabled, setLocalDisabled] =
    useState<string[]>(disabledFromUser);
  useEffect(() => {
    setLocalDisabled(disabledFromUser);
  }, [disabledFromUser]);

  const refreshModules = useCallback(async () => {
    if (!token) {
      setAvailableModules([]);
      return;
    }
    try {
      const resp = await fetch(`${API_AGENT_PREFIX}/agent/modules`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!resp.ok) return;
      const mods = (await resp.json()) as ModuleInfo[];
      setAvailableModules(mods);
    } catch {
      /* swallow — UI просто покажет пустой список */
    }
  }, [token]);

  useEffect(() => {
    void refreshModules();
  }, [refreshModules]);

  const openConnectorsDirectory = useCallback(() => {
    setDirectoryOpen(true);
  }, []);

  const openConnectorsManage = useCallback(() => {
    setManageOpen(true);
  }, []);

  const openContextModal = useCallback(() => {
    setContextModalOpen(true);
  }, [setContextModalOpen]);

  const closeContextModal = useCallback(() => {
    setContextModalOpen(false);
  }, [setContextModalOpen]);

  const enabledModules = useMemo(() => {
    const disabledSet = new Set(localDisabled);
    return availableModules.reduce<Record<string, boolean>>((acc, m) => {
      acc[m.id] = !disabledSet.has(m.id);
      return acc;
    }, {});
  }, [availableModules, localDisabled]);

  const setModulesState = useCallback(
    async (updates: Record<string, boolean>) => {
      if (!token) return;
      const prev = localDisabled;
      const nextSet = new Set(prev);
      Object.entries(updates).forEach(([moduleId, enabled]) => {
        if (enabled) {
          nextSet.delete(moduleId);
        } else {
          nextSet.add(moduleId);
        }
      });
      const next = Array.from(nextSet);

      setLocalDisabled(next); // optimistic
      try {
        const resp = await fetch(`${API_AGENT_PREFIX}/auth/users/me`, {
          method: "PATCH",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({ settings: { disabledModules: next } }),
        });
        if (!resp.ok) throw new Error(`PATCH failed: ${resp.status}`);
        await refreshUser();
      } catch {
        setLocalDisabled(prev);
      }
    },
    [localDisabled, token, refreshUser],
  );

  const toggleModule = useCallback(
    async (moduleId: string, enabled: boolean) => {
      return setModulesState({ [moduleId]: enabled });
    },
    [setModulesState],
  );

  return (
    <UserInfoContext.Provider
      value={{
        mcpTools,
        setMcpTools,
        connectors,
        openConnectorsDirectory,
        openConnectorsManage,
        openContextModal,
        closeContextModal,
        enabledModules,
        toggleModule,
        setModulesState,
        availableModules,
        refreshModules,
      }}
    >
      {children}
      <ConnectorsDirectoryModal
        isOpen={directoryOpen}
        onClose={() => setDirectoryOpen(false)}
        api={connectors}
        onManage={() => {
          setDirectoryOpen(false);
          setManageOpen(true);
        }}
      />
      <ConnectorsManageModal
        isOpen={manageOpen}
        onClose={() => setManageOpen(false)}
        api={connectors}
        onAdd={() => {
          setManageOpen(false);
          setDirectoryOpen(true);
        }}
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
