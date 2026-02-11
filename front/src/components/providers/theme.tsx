import React, {
  createContext,
  useContext,
  useState,
  useEffect,
  useRef,
  useCallback,
  useMemo,
  PropsWithChildren,
} from "react";
import { useAuth } from "@/components/providers/auth.tsx";

export type ThemeMode = "system" | "light" | "dark";

interface ThemeContextType {
  /** Текущий режим темы: system, light или dark */
  themeMode: ThemeMode;
  /** Установить режим темы */
  setThemeMode: (mode: ThemeMode) => void;
  /** Вычисленное значение: темная тема активна или нет */
  isDark: boolean;
  /** Переключить между light и dark (system -> dark) */
  toggleTheme: () => void;
}

const ThemeContext = createContext<ThemeContextType | null>(null);

const getSystemPrefersDark = (): boolean => {
  return (
    window.matchMedia &&
    window.matchMedia("(prefers-color-scheme: dark)").matches
  );
};

export const ThemeProvider: React.FC<PropsWithChildren> = ({ children }) => {
  const { user } = useAuth();

  const [themeMode, setThemeModeState] = useState<ThemeMode>(() => {
    // Начальное значение из настроек пользователя (если уже загружен)
    const savedTheme = user?.settings?.theme as ThemeMode | undefined;
    if (savedTheme === "light" || savedTheme === "dark" || savedTheme === "system") {
      return savedTheme;
    }
    return "system";
  });

  const [systemPrefersDark, setSystemPrefersDark] = useState<boolean>(
    getSystemPrefersDark
  );

  const didInitRef = useRef<boolean>(false);

  // Синхронизация темы из настроек пользователя
  useEffect(() => {
    if (!user?.settings) return;
    const savedTheme = user.settings.theme as ThemeMode | undefined;
    if (savedTheme && (savedTheme === "light" || savedTheme === "dark" || savedTheme === "system")) {
      setThemeModeState(savedTheme);
    }
  }, [user]);

  // Вычисляем итоговое значение isDark
  const isDark = useMemo(() => {
    if (themeMode === "system") {
      return systemPrefersDark;
    }
    return themeMode === "dark";
  }, [themeMode, systemPrefersDark]);

  // Инициализация темы (без анимации)
  useEffect(() => {
    if (isDark) {
      document.documentElement.classList.add("dark");
    } else {
      document.documentElement.classList.remove("dark");
    }
    didInitRef.current = true;
  }, []);

  // Реакция на изменения системной темы
  useEffect(() => {
    if (!window.matchMedia) return;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = (e: MediaQueryListEvent) => {
      setSystemPrefersDark(e.matches);
    };
    if (media.addEventListener) {
      media.addEventListener("change", onChange);
    } else {
      // @ts-ignore: Safari
      media.addListener(onChange);
    }
    return () => {
      if (media.removeEventListener) {
        media.removeEventListener("change", onChange);
      } else {
        // @ts-ignore: Safari
        media.removeListener(onChange);
      }
    };
  }, []);

  // Применение темы при переключении (с анимацией)
  useEffect(() => {
    if (!didInitRef.current) return;
    const root = document.documentElement;
    root.classList.add("theme-animating");
    const timeout = window.setTimeout(() => {
      root.classList.remove("theme-animating");
    }, 300);
    if (isDark) {
      root.classList.add("dark");
    } else {
      root.classList.remove("dark");
    }
    return () => window.clearTimeout(timeout);
  }, [isDark]);

  const setThemeMode = useCallback((mode: ThemeMode) => {
    setThemeModeState(mode);
  }, []);

  const toggleTheme = useCallback(() => {
    setThemeModeState((prev) => {
      if (prev === "light") return "dark";
      if (prev === "dark") return "light";
      // system -> переключаем на противоположную текущей системной
      return systemPrefersDark ? "light" : "dark";
    });
  }, [systemPrefersDark]);

  return (
    <ThemeContext.Provider value={{ themeMode, setThemeMode, isDark, toggleTheme }}>
      {children}
    </ThemeContext.Provider>
  );
};

export const useTheme = () => {
  const context = useContext(ThemeContext);
  if (context === null) {
    throw new Error("useTheme must be used within a ThemeProvider");
  }
  return context;
};
