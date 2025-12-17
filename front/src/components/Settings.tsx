import React, { createContext, useContext, useEffect, useState } from "react";
import { Secret } from "@/interfaces.ts";

type Settings = {
  autoApprove: boolean;
  sideBarOpen: boolean;
  contextInstructions: string;
  contextSecrets: Array<Secret>;
  activeCollections: Record<string, boolean>;
};

interface SettingsProps {
  children: any[] | any;
}

const defaultSettings: Settings = {
  autoApprove: false,
  sideBarOpen: true,
  contextInstructions: "",
  contextSecrets: [],
  activeCollections: {},
};

const SettingsContext = createContext<{
  settings: Settings;
  setSettings: React.Dispatch<React.SetStateAction<Settings>>;
}>({ settings: defaultSettings, setSettings: () => {} });

export const SettingsProvider = ({ children }: SettingsProps) => {
  const [settings, setSettings] = useState<Settings>(() => {
    const saved = localStorage.getItem("app-settings");
    if (saved) {
      try {
        const parsed = JSON.parse(saved) as Partial<Settings>;
        // Мержим с дефолтными настройками:
        return { ...defaultSettings, ...parsed };
      } catch {
        // Если JSON кривой — просто возвращаем дефолты
        return defaultSettings;
      }
    }
    return defaultSettings;
  });

  useEffect(() => {
    localStorage.setItem("app-settings", JSON.stringify(settings));
  }, [settings]);

  return (
    <SettingsContext.Provider value={{ settings, setSettings }}>
      {children}
    </SettingsContext.Provider>
  );
};

// Хук для удобного доступа
export const useSettings = () => useContext(SettingsContext);
