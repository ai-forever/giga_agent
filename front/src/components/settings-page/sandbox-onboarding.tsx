import React, { useState } from "react";
import { ChevronDown, HelpCircle, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { cn } from "@/lib/utils";
import {
  getOnboardingState,
  updateOnboardingState,
} from "@/components/onboarding/onboardingState";

const SandboxOnboarding: React.FC = () => {
  const [dismissed, setDismissed] = useState(
    () => getOnboardingState().sandbox_settings_seen,
  );
  const [expanded, setExpanded] = useState(false);

  const handleDismiss = () => {
    updateOnboardingState({ sandbox_settings_seen: true });
    setDismissed(true);
  };

  if (dismissed) return null;

  return (
    <Alert variant="info" className="relative">
      <HelpCircle />
      <AlertTitle>Что такое Sandbox?</AlertTitle>
      <Button
        variant="ghost"
        size="icon"
        onClick={handleDismiss}
        aria-label="Скрыть подсказку"
        className="absolute right-2 top-2 h-7 w-7 text-current hover:bg-black/5 dark:hover:bg-white/10"
      >
        <X className="size-4" />
      </Button>
      <AlertDescription>
        <p>
          Sandbox — это изолированная среда, в которой агент запускает код,
          работает с файлами и использует большинство инструментов. Без
          настроенного и активного провайдера агент не сможет выполнять эти
          действия. Создайте провайдера кнопкой «Добавить», а затем активируйте
          его.
        </p>
        <button
          type="button"
          onClick={() => setExpanded((prev) => !prev)}
          className="mt-1 inline-flex items-center gap-1 font-medium hover:underline"
        >
          <ChevronDown
            className={cn(
              "size-4 transition-transform",
              expanded && "rotate-180",
            )}
          />
          {expanded ? "Скрыть подробности" : "Подробнее о LOCAL_DOCKER"}
        </button>
        {expanded && (
          <div className="mt-1 space-y-2">
            <p>
              <span className="font-medium">LOCAL_DOCKER</span> запускает
              sandbox локально в Docker-контейнере на этом же сервере. Это
              удобный вариант для локальной работы: не нужны сторонние сервисы,
              достаточно установленного и запущенного Docker.
            </p>
            <p>
              Опция <span className="font-mono font-medium">not_remove</span>{" "}
              («Не удалять контейнер») определяет, что происходит с контейнером
              после остановки sandbox:
            </p>
            <ul className="list-disc space-y-1 pl-5">
              <li>
                <span className="font-medium">Выключена (по умолчанию):</span>{" "}
                контейнер удаляется после остановки, и при следующем запуске
                создаётся новый — чистое окружение каждый раз.
              </li>
              <li>
                <span className="font-medium">Включена:</span> контейнер не
                удаляется и переиспользуется при следующем запуске.
                Установленные пакеты и файлы вне рабочей директории сохраняются,
                а запуск происходит быстрее. Если поднять Jupyter в
                переиспользуемом контейнере не удаётся, он пересоздаётся
                автоматически.
              </li>
            </ul>
          </div>
        )}
      </AlertDescription>
    </Alert>
  );
};

export default SandboxOnboarding;
