import React, {
  PropsWithChildren,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import { type MCPTool } from "@/components/mcp/mcp-modal.tsx";
import ContextModal from "@/components/modals/context-modal.tsx";
import ConnectorsModal, {
  type ConnectorsTab,
} from "@/components/mcp/connectors/connectors-modal.tsx";
import { useConnectors } from "@/components/mcp/connectors/use-connectors.ts";
import { API_AGENT_PREFIX } from "@/config.ts";
import { useAuth } from "@/components/providers/auth.tsx";
import {
  UserInfoContext,
  type ModuleInfo,
} from "@/components/providers/user-info-context.ts";

const readDisabledFromUser = (user: unknown): string[] => {
  const settings = (user as { settings?: unknown } | null | undefined)
    ?.settings;
  if (!settings || typeof settings !== "object") return [];
  const raw = (settings as Record<string, unknown>).disabledModules;
  if (!Array.isArray(raw)) return [];
  return raw.filter((x): x is string => typeof x === "string");
};

export const UserInfoProvider: React.FC<PropsWithChildren> = ({ children }) => {
  const [mcpTools, setMcpTools] = useState<MCPTool[]>([]);
  const connectors = useConnectors();
  const [connectorsOpen, setConnectorsOpen] = useState(false);
  const [connectorsTab, setConnectorsTab] = useState<ConnectorsTab>("catalog");
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

  const openConnectors = useCallback((tab: ConnectorsTab = "catalog") => {
    setConnectorsTab(tab);
    setConnectorsOpen(true);
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
        connectors,
        openConnectors,
        openContextModal,
        closeContextModal,
        enabledModules,
        toggleModule,
        availableModules,
        refreshModules,
      }}
    >
      {children}
      <ConnectorsModal
        isOpen={connectorsOpen}
        onClose={() => setConnectorsOpen(false)}
        api={connectors}
        initialTab={connectorsTab}
      />
      <ContextModal isOpen={contextModalOpen} onClose={closeContextModal} />
    </UserInfoContext.Provider>
  );
};
