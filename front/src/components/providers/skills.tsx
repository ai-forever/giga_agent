import React, {
  PropsWithChildren,
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
} from "react";

import { API_AGENT_PREFIX } from "@/config.ts";
import { useAuth } from "@/components/providers/auth.tsx";

export interface SkillInfo {
  id: string;
  name: string;
  description: string | null;
  is_enabled: boolean;
}

interface UseSkillsReturn {
  skills: SkillInfo[];
  selectedSkills: Record<string, boolean>;
  selectedSkillNames: string[];
  toggleSkill: (name: string, on: boolean) => void;
  clearSelectedSkills: () => void;
  fetchSkills: () => Promise<void>;
  skillsLoading: boolean;
}

const SkillsContext = createContext<UseSkillsReturn | null>(null);

export const SkillsProvider: React.FC<PropsWithChildren> = ({ children }) => {
  const { token } = useAuth();
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [selectedSkills, setSelectedSkills] = useState<Record<string, boolean>>(
    {},
  );
  const [skillsLoading, setSkillsLoading] = useState(false);

  const fetchSkills = useCallback(async () => {
    if (!token) return;
    setSkillsLoading(true);
    try {
      const resp = await fetch(`${API_AGENT_PREFIX}/skills/`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!resp.ok) return;
      const data = (await resp.json()) as SkillInfo[];
      setSkills(data.filter((s) => s.is_enabled));
    } catch {
      /* swallow */
    } finally {
      setSkillsLoading(false);
    }
  }, [token]);

  const toggleSkill = useCallback((name: string, on: boolean) => {
    setSelectedSkills((prev) => {
      const next = { ...prev };
      if (on) next[name] = true;
      else delete next[name];
      return next;
    });
  }, []);

  const clearSelectedSkills = useCallback(() => {
    setSelectedSkills({});
  }, []);

  const selectedSkillNames = useMemo(
    () => Object.keys(selectedSkills).filter((k) => selectedSkills[k]),
    [selectedSkills],
  );

  const value = useMemo<UseSkillsReturn>(
    () => ({
      skills,
      selectedSkills,
      selectedSkillNames,
      toggleSkill,
      clearSelectedSkills,
      fetchSkills,
      skillsLoading,
    }),
    [
      skills,
      selectedSkills,
      selectedSkillNames,
      toggleSkill,
      clearSelectedSkills,
      fetchSkills,
      skillsLoading,
    ],
  );

  return (
    <SkillsContext.Provider value={value}>{children}</SkillsContext.Provider>
  );
};

export const useSkills = () => {
  const ctx = useContext(SkillsContext);
  if (!ctx) {
    throw new Error("useSkills must be used within a SkillsProvider");
  }
  return ctx;
};
