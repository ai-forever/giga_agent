import React, {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  useMemo,
  PropsWithChildren,
} from "react";
import { API_AGENT_PREFIX } from "@/config.ts";
import type { LLMResponse } from "@/components/settings-page/forms/types";

const AUTH_TOKEN_KEY = "auth_token";

interface User {
  id: string;
  email: string;
  first_name?: string | null;
  last_name?: string | null;
  is_active: boolean;
  is_superuser: boolean;
  experimental_mode: boolean;
  settings: Record<string, unknown> | null;
  secrets: Record<string, unknown> | null;
  llm_id: string | null;
  fast_llm_id: string | null;
  embedding_id: string | null;
  sandbox_provider_id: string | null;
  image_generator_id: string | null;
  search_engine_id: string | null;
}

interface AuthContextType {
  isAuthenticated: boolean;
  isLoading: boolean;
  user: User | null;
  token: string | null;
  llms: LLMResponse[];
  currentLlm: LLMResponse | null;
  isLoadingLLMs: boolean;
  hasLoadedLLMs: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  refreshUser: () => Promise<void>;
  refreshLLMs: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | null>(null);

export const AuthProvider: React.FC<PropsWithChildren> = ({ children }) => {
  const [token, setToken] = useState<string | null>(() => {
    return localStorage.getItem(AUTH_TOKEN_KEY);
  });
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [llms, setLlms] = useState<LLMResponse[]>([]);
  const [isLoadingLLMs, setIsLoadingLLMs] = useState(false);
  const [hasLoadedLLMs, setHasLoadedLLMs] = useState(false);

  const isAuthenticated = !!token && !!user;
  const currentLlm = useMemo(
    () => llms.find((llm) => llm.id === user?.llm_id) ?? null,
    [llms, user?.llm_id],
  );

  const logout = useCallback(() => {
    void fetch(`${API_AGENT_PREFIX}/auth/logout`, {
      method: "POST",
      credentials: "include",
    });
    localStorage.removeItem(AUTH_TOKEN_KEY);
    setToken(null);
    setUser(null);
    setLlms([]);
    setIsLoadingLLMs(false);
    setHasLoadedLLMs(false);
  }, []);

  const checkAuth = useCallback(async (authToken: string) => {
    try {
      const response = await fetch(`${API_AGENT_PREFIX}/auth/users/me`, {
        credentials: "include",
        headers: {
          Authorization: `Bearer ${authToken}`,
        },
      });

      if (!response.ok) {
        throw new Error("Invalid token");
      }

      const userData: User = await response.json();
      setUser(userData);
      return true;
    } catch {
      return false;
    }
  }, []);

  const login = useCallback(
    async (email: string, password: string) => {
      const formData = new FormData();
      formData.append("username", email);
      formData.append("password", password);

      const response = await fetch(`${API_AGENT_PREFIX}/auth/token`, {
        method: "POST",
        credentials: "include",
        body: formData,
      });

      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.detail || "Неверный email или пароль");
      }

      const data = await response.json();
      const newToken = data.access_token;

      localStorage.setItem(AUTH_TOKEN_KEY, newToken);
      setToken(newToken);
      setHasLoadedLLMs(false);

      await checkAuth(newToken);
    },
    [checkAuth],
  );

  const refreshUser = useCallback(async () => {
    if (token) {
      await checkAuth(token);
    }
  }, [token, checkAuth]);

  const refreshLLMs = useCallback(async () => {
    if (!token) {
      setLlms([]);
      setHasLoadedLLMs(false);
      return;
    }

    setIsLoadingLLMs(true);
    setHasLoadedLLMs(false);
    try {
      const response = await fetch(`${API_AGENT_PREFIX}/llms`, {
        credentials: "include",
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      if (!response.ok) {
        throw new Error("Failed to load LLMs");
      }

      const data: LLMResponse[] = await response.json();
      setLlms(data);
      setHasLoadedLLMs(true);
    } catch {
      setLlms([]);
      setHasLoadedLLMs(false);
    } finally {
      setIsLoadingLLMs(false);
    }
  }, [token]);

  useEffect(() => {
    if (!token || !user) {
      setLlms([]);
      setIsLoadingLLMs(false);
      setHasLoadedLLMs(false);
      return;
    }

    void refreshLLMs();
  }, [token, user?.id, refreshLLMs]);

  useEffect(() => {
    const initAuth = async () => {
      if (token) {
        const isValid = await checkAuth(token);
        if (!isValid) {
          logout();
        }
      }
      setIsLoading(false);
    };

    initAuth();
  }, []);

  return (
    <AuthContext.Provider
      value={{
        isAuthenticated,
        isLoading,
        user,
        token,
        llms,
        currentLlm,
        isLoadingLLMs,
        hasLoadedLLMs,
        login,
        logout,
        refreshUser,
        refreshLLMs,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (context === null) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
};
