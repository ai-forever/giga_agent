import { EXPERIMENTAL_MODE } from "@/config.ts";
import { useAuth } from "@/components/providers/auth.tsx";

/**
 * localStorage-ключ dev-оверрайда. Если в консоли выполнить
 * `localStorage.setItem('giga_agent_advanced_settings', '1')` и перезагрузить
 * страницу — скрытые в экспериментальном режиме настройки/пикеры снова
 * показываются (только в текущем браузере).
 */
export const ADVANCED_OVERRIDE_KEY = "giga_agent_advanced_settings";

export interface ExperimentalModeState {
  /**
   * Экспериментальный режим реально активен для текущего пользователя:
   * включён env-флаг (app-config) И флаг у самого пользователя.
   * Управляет маршрутизацией через граф `giga_agent_experimental`.
   */
  experimentalActive: boolean;
  /**
   * Нужно ли скрывать продвинутые настройки (ModelPicker, вкладки настроек,
   * селекты моделей/движков, тумблер автономности). Скрываем только для
   * НЕ-админов в экспериментальном режиме, если не выставлен dev-оверрайд.
   */
  hideAdvanced: boolean;
}

const readAdvancedOverride = (): boolean => {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(ADVANCED_OVERRIDE_KEY) === "1";
  } catch {
    return false;
  }
};

export function useExperimentalMode(): ExperimentalModeState {
  const { user } = useAuth();
  const experimentalActive =
    EXPERIMENTAL_MODE && user?.experimental_mode === true;
  const hideAdvanced =
    experimentalActive && !user?.is_superuser && !readAdvancedOverride();
  return { experimentalActive, hideAdvanced };
}
