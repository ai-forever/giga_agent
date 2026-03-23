import React, {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  PropsWithChildren,
} from "react";
import { API_AGENT_PREFIX } from "@/config.ts";

const AUTH_TOKEN_KEY = "auth_token";

interface User {
  id: string;
  email: string;
  first_name?: string | null;
  last_name?: string | null;
  is_active: boolean;
  is_superuser: boolean;
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
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | null>(null);

export const AuthProvider: React.FC<PropsWithChildren> = ({ children }) => {
  const [token, setToken] = useState<string | null>(() => {
    return localStorage.getItem(AUTH_TOKEN_KEY);
  });
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const isAuthenticated = !!token && !!user;

  const logout = useCallback(() => {
    void fetch(`${API_AGENT_PREFIX}/auth/logout`, {
      method: "POST",
      credentials: "include",
    });
    localStorage.removeItem(AUTH_TOKEN_KEY);
    setToken(null);
    setUser(null);
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

      await checkAuth(newToken);
    },
    [checkAuth],
  );

  const refreshUser = useCallback(async () => {
    if (token) {
      await checkAuth(token);
    }
  }, [token, checkAuth]);

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
        login,
        logout,
        refreshUser,
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
