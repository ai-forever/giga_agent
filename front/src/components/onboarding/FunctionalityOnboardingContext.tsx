import React, { createContext, useContext, useState, useCallback } from "react";
import {
  clearOnboardingState,
  getOnboardingState,
  updateOnboardingState,
} from "./onboardingState";

export const TIP_IDS = {
  CHAT_FEATURE_TOUR: "chat_feature_tour_seen",
  RESPONSE_ATTACHMENT_TIP: "response_attachment_tip_seen",
} as const;

type TipsMap = Record<string, boolean>;

function loadTips(): TipsMap {
  const state = getOnboardingState();
  return {
    [TIP_IDS.CHAT_FEATURE_TOUR]: state.chat_feature_tour_seen,
    [TIP_IDS.RESPONSE_ATTACHMENT_TIP]: state.response_attachment_tip_seen,
  };
}

function persistTips(tips: TipsMap) {
  updateOnboardingState({
    chat_feature_tour_seen: !!tips[TIP_IDS.CHAT_FEATURE_TOUR],
    response_attachment_tip_seen: !!tips[TIP_IDS.RESPONSE_ATTACHMENT_TIP],
  });
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
  clearOnboardingState();
};
