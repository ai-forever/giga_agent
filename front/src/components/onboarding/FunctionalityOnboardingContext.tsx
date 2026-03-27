import React, { createContext, useContext, useState, useCallback } from "react";

const TIPS_STORAGE_KEY = "feature_guidance_state";

export const TIP_IDS = {
  STARTUP_TOUR: "startup_tour",
  ATTACHMENT_SELECTION: "attachment_selection",
} as const;

type TipsMap = Record<string, boolean>;

function loadTips(): TipsMap {
  try {
    return JSON.parse(
      localStorage.getItem(TIPS_STORAGE_KEY) || "{}",
    );
  } catch {
    return {};
  }
}

function persistTips(tips: TipsMap) {
  localStorage.setItem(TIPS_STORAGE_KEY, JSON.stringify(tips));
}

interface FunctionalityOnboardingContextValue {
  isTipComplete: (id: string) => boolean;
  markTipComplete: (id: string) => void;
  tourActive: boolean;
  setTourActive: React.Dispatch<React.SetStateAction<boolean>>;
}

const FunctionalityOnboardingContext =
  createContext<FunctionalityOnboardingContextValue>({
    isTipComplete: () => false,
    markTipComplete: () => {},
    tourActive: false,
    setTourActive: () => {},
  });

export const useFunctionalityOnboarding = () =>
  useContext(FunctionalityOnboardingContext);

export const FunctionalityOnboardingProvider: React.FC<{
  children: React.ReactNode;
}> = ({ children }) => {
  const [tourActive, setTourActive] = useState(false);
  const [tips, setTips] = useState<TipsMap>(loadTips);

  const isTipComplete = useCallback((id: string) => !!tips[id], [tips]);

  const markTipComplete = useCallback((id: string) => {
    setTips((prev) => {
      const next = { ...prev, [id]: true };
      persistTips(next);
      return next;
    });
  }, []);

  return (
    <FunctionalityOnboardingContext.Provider
      value={{
        isTipComplete,
        markTipComplete,
        tourActive,
        setTourActive,
      }}
    >
      {children}
    </FunctionalityOnboardingContext.Provider>
  );
};

export const resetAllOnboardingTips = (): void => {
  localStorage.removeItem(TIPS_STORAGE_KEY);
};
