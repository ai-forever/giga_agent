import React, {
  createContext,
  PropsWithChildren,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import McpServerModal, { MCPTool } from "@/components/mcp/mcp-modal.tsx";
import ContextModal from "@/components/modals/context-modal.tsx";
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
  openMcpModal: () => void;
  closeMcpModal: () => void;
  openContextModal: () => void;
  closeContextModal: () => void;
  enabledModules: Record<string, boolean>;
  toggleModule: (moduleId: string, enabled: boolean) => Promise<void>;
  availableModules: ModuleInfo[];
  refreshModules: () => void;
};

const UserInfoContext = createContext<UserInfoContextType | null>(null);

export const UserInfoProvider: React.FC<PropsWithChildren> = ({ children }) => {
  const [mcpTools, setMcpTools] = useState<MCPTool[]>([]);
  const [mcpModalOpen, setMcpModalOpen] = useState(false);
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

  const enabledModules = useMemo(() => {
    const disabledSet = new Set(localDisabled);
    return availableModules.reduce<Record<string, boolean>>((acc, m) => {
      acc[m.id] = !disabledSet.has(m.id);
      return acc;
    }, {});
  }, [availableModules, localDisabled]);

  const toggleModule = useCallback(
    async (moduleId: string, enabled: boolean) => {
      if (!token) return;
      const prev = localDisabled;
      const next = enabled
        ? prev.filter((x) => x !== moduleId)
        : Array.from(new Set([...prev, moduleId]));
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
        // Откатываем оптимистичное обновление при ошибке.
        setLocalDisabled(prev);
      }
    },
    [localDisabled, token, refreshUser],
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
        availableModules,
        refreshModules,
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
