import React, { useState, useCallback, useEffect } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import {
  ArrowRight,
  ArrowLeft,
  Check,
  Plug,
  Brain,
  Settings,
  Sparkles,
  Box,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";

const ONBOARDING_COMPLETE_KEY = "setup_complete";

interface OnboardingStep {
  id: string;
  title: string;
  description: string;
  settingsTab: string | null;
  icon: React.ReactNode;
}

const STEPS: OnboardingStep[] = [
  {
    id: "welcome",
    title: "Добро пожаловать в GigaAgent!",
    description:
      "Для начала работы необходимо настроить подключения и модели. Мы проведём вас по основным шагам настройки.",
    settingsTab: null,
    icon: <Sparkles className="size-6" />,
  },
  {
    id: "connectors",
    title: "Шаг 1: Коннекторы",
    description:
      "Добавьте подключения к AI-сервисам (GigaChat, OpenAI и др.). Коннекторы содержат API-ключи и настройки доступа к провайдерам моделей.",
    settingsTab: "connectors",
    icon: <Plug className="size-6" />,
  },
  {
    id: "llm",
    title: "Шаг 2: Языковые модели (LLM)",
    description:
      "Создайте LLM-модели, привязанные к коннекторам. Укажите конкретные модели, которые будет использовать агент для генерации ответов.",
    settingsTab: "llm",
    icon: <Brain className="size-6" />,
  },
  {
    id: "sandbox",
    title: "Шаг 3: Sandbox",
    description:
      "Настройте провайдер изолированной среды выполнения кода (Sandbox). Без него агент не сможет запускать код, работать с файлами и использовать большинство инструментов.",
    settingsTab: "sandbox",
    icon: <Box className="size-6" />,
  },
  {
    id: "general",
    title: "Шаг 4: Основные настройки",
    description:
      "Выберите модель по умолчанию и другие базовые настройки. Это определит, какая модель будет использоваться в чате.",
    settingsTab: "general",
    icon: <Settings className="size-6" />,
  },
  {
    id: "done",
    title: "Готово!",
    description:
      "Настройка завершена. Теперь вы можете начать общение с агентом. Дополнительные настройки (Embeddings, Search, Image) доступны в разделе Настройки.",
    settingsTab: null,
    icon: <Check className="size-6" />,
  },
];

export const isOnboardingComplete = (): boolean => {
  return localStorage.getItem(ONBOARDING_COMPLETE_KEY) === "true";
};

export const markOnboardingComplete = (): void => {
  localStorage.setItem(ONBOARDING_COMPLETE_KEY, "true");
  window.dispatchEvent(new CustomEvent("setup-state-change"));
};

export const resetOnboarding = (): void => {
  localStorage.removeItem(ONBOARDING_COMPLETE_KEY);
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
  const isFirst = currentStep === 0;
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

  const handlePrev = useCallback(() => {
    if (isFirst) return;
    const prev = currentStep - 1;
    setCurrentStep(prev);
    navigateToStep(prev);
  }, [currentStep, isFirst, navigateToStep]);

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
          className="fixed bottom-4 left-1/2 -translate-x-1/2 z-[9999] w-full max-w-xl px-4"
        >
          <div className="bg-card border border-border rounded-xl shadow-2xl overflow-hidden">
            {/* Progress bar */}
            <div className="h-1 bg-muted">
              <motion.div
                className="h-full bg-primary"
                initial={false}
                animate={{
                  width: `${(currentStep / (STEPS.length - 1)) * 100}%`,
                }}
                transition={{ duration: 0.3, ease: "easeInOut" }}
              />
            </div>

            <div className="p-5">
              {/* Header with step indicator and close */}
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2 text-muted-foreground text-xs">
                  {STEPS.map((_, i) => (
                    <div
                      key={i}
                      className={`size-2 rounded-full transition-colors ${
                        i === currentStep
                          ? "bg-primary"
                          : i < currentStep
                            ? "bg-primary/40"
                            : "bg-muted-foreground/20"
                      }`}
                    />
                  ))}
                </div>
                <button
                  onClick={handleSkip}
                  className="text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
                  title="Пропустить"
                >
                  <X className="size-4" />
                </button>
              </div>

              {/* Step content */}
              <AnimatePresence mode="wait">
                <motion.div
                  key={step.id}
                  initial={{ opacity: 0, x: 20 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -20 }}
                  transition={{ duration: 0.2 }}
                >
                  <div className="flex items-start gap-3">
                    <div className="flex-shrink-0 mt-0.5 text-primary">
                      {step.icon}
                    </div>
                    <div className="min-w-0">
                      <h3 className="font-semibold text-base mb-1">
                        {step.title}
                      </h3>
                      <p className="text-sm text-muted-foreground leading-relaxed">
                        {step.description}
                      </p>
                    </div>
                  </div>
                </motion.div>
              </AnimatePresence>

              {/* Actions */}
              <div className="flex items-center justify-between mt-4 pt-3 border-t border-border">
                <div>
                  {!isFirst && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={handlePrev}
                      className="gap-1"
                    >
                      <ArrowLeft className="size-4" />
                      Назад
                    </Button>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  {!isLast && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={handleSkip}
                      className="text-muted-foreground"
                    >
                      Пропустить
                    </Button>
                  )}
                  <Button size="sm" onClick={handleNext} className="gap-1">
                    {isLast ? (
                      <>
                        Начать работу
                        <Check className="size-4" />
                      </>
                    ) : isFirst ? (
                      <>
                        Начать настройку
                        <ArrowRight className="size-4" />
                      </>
                    ) : (
                      <>
                        Далее
                        <ArrowRight className="size-4" />
                      </>
                    )}
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
};

export default OnboardingWizard;
