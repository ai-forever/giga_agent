import React, { useState, useCallback, useEffect } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { Button } from "@/components/ui/button";
import {
  clearOnboardingState,
  getOnboardingState,
  updateOnboardingState,
} from "./onboardingState";

interface OnboardingStep {
  id: string;
  title: string;
  description: string;
  settingsTab: string | null;
}

const STEPS: OnboardingStep[] = [
  {
    id: "welcome",
    title: "Добро пожаловать в GigaAgent!",
    description:
      "Для начала работы необходимо настроить подключения и модели. Мы проведём вас по основным шагам настройки.",
    settingsTab: null,
  },
  {
    id: "connectors",
    title: "Подключения",
    description:
      "Добавьте подключения к AI-сервисам (GigaChat, OpenAI и др.). Подключения содержат API-ключи и настройки доступа к провайдерам моделей.",
    settingsTab: "connectors",
  },
  {
    id: "llm",
    title: "Языковые модели (LLM)",
    description:
      "Создайте LLM-модели, привязанные к подключениям. Укажите конкретные модели, которые будет использовать агент для генерации ответов.",
    settingsTab: "llm",
  },
  {
    id: "sandbox",
    title: "Sandbox",
    description:
      "Настройте провайдер изолированной среды выполнения кода (Sandbox). Без него агент не сможет запускать код, работать с файлами и использовать большинство инструментов.",
    settingsTab: "sandbox",
  },
  {
    id: "general",
    title: "Основные настройки",
    description:
      "Выберите модель по умолчанию и другие базовые настройки. Это определит, какая модель будет использоваться в чате.",
    settingsTab: "general",
  },
];

export const isOnboardingComplete = (): boolean => {
  return getOnboardingState().setup_seen;
};

export const markOnboardingComplete = (): void => {
  updateOnboardingState({ setup_seen: true });
  window.dispatchEvent(new CustomEvent("setup-state-change"));
};

export const resetOnboarding = (): void => {
  clearOnboardingState();
};

const OnboardingWizard: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const [currentStep, setCurrentStep] = useState(0);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (!isOnboardingComplete()) {
      setVisible(true);
    }
  }, []);

  const step = STEPS[currentStep];
  const isLast = currentStep === STEPS.length - 1;

  const navigateToStep = useCallback(
    (stepIndex: number) => {
      const target = STEPS[stepIndex];
      if (target.settingsTab) {
        const path = `/settings/${target.settingsTab}`;
        if (location.pathname !== path) {
          navigate(path);
        }
      }
    },
    [navigate, location.pathname],
  );

  const handleNext = useCallback(() => {
    if (isLast) {
      markOnboardingComplete();
      setVisible(false);
      return;
    }
    const next = currentStep + 1;
    setCurrentStep(next);
    navigateToStep(next);
  }, [currentStep, isLast, navigate, navigateToStep]);

  const handleSkip = useCallback(() => {
    markOnboardingComplete();
    setVisible(false);
  }, []);

  if (!visible) return null;

  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          initial={{ y: 100, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          exit={{ y: 100, opacity: 0 }}
          transition={{ type: "spring", damping: 25, stiffness: 300 }}
          className="fixed bottom-4 left-1/2 -translate-x-1/2 z-[9999] w-full max-w-md px-4"
        >
          <div className="bg-card dark:bg-zinc-800 border border-border rounded-xl shadow-xl overflow-hidden">
            <div className="p-4">
              {/* Step content */}
              <AnimatePresence mode="wait">
                <motion.div
                  key={step.id}
                  initial={{ opacity: 0, x: 20 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -20 }}
                  transition={{ duration: 0.2 }}
                >
                  <div className="min-w-0">
                    <div className="mb-1.5 flex items-start justify-between gap-2">
                      <h3 className="font-semibold text-sm leading-snug">
                        {step.title}
                      </h3>
                      {STEPS.length > 1 && (
                        <div className="text-xs text-muted-foreground shrink-0">
                          {currentStep + 1}/{STEPS.length}
                        </div>
                      )}
                    </div>
                    <p className="text-xs text-muted-foreground leading-relaxed">
                      {step.description}
                    </p>
                  </div>
                </motion.div>
              </AnimatePresence>

              <div className="flex items-center justify-end gap-2 mt-3 pt-3 border-t border-border">
                {!isLast && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={handleSkip}
                    className="h-8 text-xs text-muted-foreground"
                  >
                    Пропустить
                  </Button>
                )}
                <Button size="sm" onClick={handleNext} className="h-8 text-xs">
                  {isLast ? "Понятно" : "Дальше"}
                </Button>
              </div>
            </div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
};

export default OnboardingWizard;
