import React, { useState, useCallback, useEffect, useRef } from "react";
import {
  Joyride,
  ACTIONS,
  EVENTS,
  STATUS,
  Step,
  TooltipRenderProps,
  EventData,
} from "react-joyride";
import { useLocation } from "react-router-dom";
import {
  ArrowRight,
  ArrowLeft,
  Check,
  Sparkles,
  Paperclip,
  ToggleRight,
  Settings2,
  MessageSquare,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { isOnboardingComplete } from "./OnboardingWizard";
import {
  useFunctionalityOnboarding,
  TIP_IDS,
} from "./FunctionalityOnboardingContext";
import { useSettings } from "@/components/Settings";

const SIDEBAR_STEP_INDEX = 4;

// ── Startup tour steps (6 total) ────────────────────────────────────────────

const STARTUP_STEPS: Step[] = [
  {
    target: "body",
    placement: "center",
    title: "Знакомство с интерфейсом",
    content:
      "Давайте познакомимся с основными возможностями чата. Мы покажем, где находятся ключевые функции.",
    skipBeacon: true,
    data: { icon: <Sparkles className="size-6" /> },
  },
  {
    target: '[data-onboarding="attachments-btn"]',
    placement: "right",
    title: "Вложения",
    content:
      "Прикрепляйте файлы к сообщениям: изображения, документы, код и другие файлы. Агент сможет их анализировать и использовать в ответе.",
    skipBeacon: true,
    spotlightPadding: 2,
    data: { icon: <Paperclip className="size-6" /> },
  },
  {
    target: '[data-onboarding="autonomy-switch"]',
    placement: "bottom",
    title: "Автономность",
    content:
      "Когда этот режим включён, агент автоматически подтверждает промежуточные действия без ожидания вашего ответа. Отключите, если хотите контролировать каждый шаг.",
    skipBeacon: true,
    data: { icon: <ToggleRight className="size-6" /> },
  },
  {
    target: '[data-onboarding="gear-menu-btn"]',
    placement: "right",
    title: "Меню настроек чата",
    content:
      "В этом меню находятся персонализация ответов, подключение инструментов (MCP) и выбор документов для RAG. Откройте его, чтобы познакомиться с каждой функцией.",
    skipBeacon: true,
    spotlightPadding: 2,
    data: { icon: <Settings2 className="size-6" /> },
  },
  {
    target: '[data-onboarding="sidebar"]',
    placement: "right",
    title: "История диалогов",
    content:
      "Все диалоги сохраняются в боковой панели. Вы можете переключаться между ними, переименовывать и удалять. Для нового диалога нажмите «Новый чат».",
    skipBeacon: true,
    targetWaitTimeout: 2000,
    data: { icon: <MessageSquare className="size-6" /> },
  },
  {
    target: "body",
    placement: "center",
    title: "Всё готово!",
    content:
      "Теперь вы знакомы с основными возможностями. Начните диалог с агентом — просто введите сообщение. Удачной работы!",
    skipBeacon: true,
    data: { icon: <Check className="size-6" /> },
  },
];

// ── Shared tooltip ──────────────────────────────────────────────────────────

const CustomTooltip: React.FC<TooltipRenderProps> = ({
  index,
  isLastStep,
  size,
  step,
  backProps,
  skipProps,
  primaryProps,
  tooltipProps,
}) => {
  const stepData = step.data as { icon?: React.ReactNode } | undefined;

  return (
    <div
      role={tooltipProps.role}
      aria-modal={tooltipProps["aria-modal"]}
      className="bg-card border border-border rounded-xl shadow-2xl overflow-hidden w-[420px] max-w-[calc(100vw-2rem)]"
      style={{ position: "relative", zIndex: 11010 }}
    >
      <div className="h-1 bg-muted">
        <div
          className="h-full bg-primary transition-all duration-300 ease-in-out"
          style={{ width: `${(index / Math.max(size - 1, 1)) * 100}%` }}
        />
      </div>

      <div className="p-5">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-1.5">
            {Array.from({ length: size }).map((_, i) => (
              <div
                key={i}
                className={`size-1.5 rounded-full transition-colors ${
                  i === index
                    ? "bg-primary"
                    : i < index
                      ? "bg-primary/40"
                      : "bg-muted-foreground/20"
                }`}
              />
            ))}
          </div>
          <button
            onClick={skipProps.onClick}
            className="text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
            title="Пропустить"
          >
            <X className="size-4" />
          </button>
        </div>

        <div className="flex items-start gap-3">
          {stepData?.icon && (
            <div className="flex-shrink-0 mt-0.5 text-primary">
              {stepData.icon}
            </div>
          )}
          <div className="min-w-0">
            {step.title && (
              <h3 className="font-semibold text-base mb-1">
                {step.title as string}
              </h3>
            )}
            <div className="text-sm text-muted-foreground leading-relaxed">
              {step.content}
            </div>
          </div>
        </div>

        <div className="flex items-center justify-between mt-4 pt-3 border-t border-border">
          <div>
            {index > 0 && (
              <Button
                variant="ghost"
                size="sm"
                onClick={backProps.onClick}
                className="gap-1"
              >
                <ArrowLeft className="size-4" />
                Назад
              </Button>
            )}
          </div>
          <div className="flex items-center gap-2">
            {!isLastStep && (
              <Button
                variant="ghost"
                size="sm"
                onClick={skipProps.onClick}
                className="text-muted-foreground"
              >
                Пропустить
              </Button>
            )}
            <Button size="sm" onClick={primaryProps.onClick} className="gap-1">
              {isLastStep ? (
                <>
                  {size <= 3 ? "Готово" : "Начать работу"}
                  <Check className="size-4" />
                </>
              ) : index === 0 && size > 3 ? (
                <>
                  Начнём
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
  );
};

// ── DOM element watcher ─────────────────────────────────────────────────────

function useElementPresent(selector: string | null): boolean {
  const [present, setPresent] = useState(false);

  useEffect(() => {
    if (!selector) {
      setPresent(false);
      return;
    }

    if (document.querySelector(selector)) {
      setPresent(true);
      return;
    }

    const observer = new MutationObserver(() => {
      if (document.querySelector(selector)) {
        setPresent(true);
        observer.disconnect();
      }
    });
    observer.observe(document.body, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, [selector]);

  return present;
}

// ── Runtime tip card (anchored to specific element) ──────────────────────────

const RuntimeTip: React.FC<{
  title: string;
  description: string;
  icon: React.ReactNode;
  targetSelector: string;
  preferredSide?: "left" | "right" | "top" | "bottom";
  onDismiss: () => void;
}> = ({
  title,
  description,
  icon,
  targetSelector,
  preferredSide = "bottom",
  onDismiss,
}) => {
  const cardRef = useRef<HTMLDivElement | null>(null);
  const [position, setPosition] = useState<{
    left: number;
    top: number;
    arrowLeft?: number;
    arrowTop?: number;
    side: "top" | "bottom" | "left" | "right";
  } | null>(null);

  useEffect(() => {
    let rafId = 0;
    let resizeObserver: ResizeObserver | null = null;

    const updatePosition = () => {
      const target = document.querySelector(
        targetSelector,
      ) as HTMLElement | null;
      const card = cardRef.current;
      if (!target || !card) {
        setPosition(null);
        return;
      }

      const rect = target.getBoundingClientRect();
      const cardWidth = card.offsetWidth;
      const cardHeight = card.offsetHeight;
      const viewportWidth = window.innerWidth;
      const viewportHeight = window.innerHeight;
      const margin = 8;
      const gap = 12;
      const targetCenterX = rect.left + rect.width / 2;
      const targetCenterY = rect.top + rect.height / 2;

      const canPlaceLeft = rect.left - cardWidth - gap >= margin;
      const canPlaceRight =
        rect.right + cardWidth + gap <= viewportWidth - margin;
      const canPlaceTop = rect.top - cardHeight - gap >= margin;
      const canPlaceBottom =
        rect.bottom + cardHeight + gap <= viewportHeight - margin;

      let side: "top" | "bottom" | "left" | "right" = "bottom";
      if (preferredSide === "left" && canPlaceLeft) side = "left";
      else if (preferredSide === "right" && canPlaceRight) side = "right";
      else if (preferredSide === "top" && canPlaceTop) side = "top";
      else if (preferredSide === "bottom" && canPlaceBottom) side = "bottom";
      else if (canPlaceLeft) side = "left";
      else if (canPlaceRight) side = "right";
      else if (canPlaceTop) side = "top";
      else side = "bottom";

      if (side === "left" || side === "right") {
        const left =
          side === "left" ? rect.left - cardWidth - gap : rect.right + gap;
        const rawTop = targetCenterY - cardHeight / 2;
        const top = Math.max(
          margin,
          Math.min(rawTop, viewportHeight - cardHeight - margin),
        );
        const arrowTop = Math.max(
          16,
          Math.min(targetCenterY - top, cardHeight - 16),
        );
        setPosition({ left, top, arrowTop, side });
        return;
      }

      const rawLeft = targetCenterX - cardWidth / 2;
      const left = Math.max(
        margin,
        Math.min(rawLeft, viewportWidth - cardWidth - margin),
      );
      const top =
        side === "top" ? rect.top - cardHeight - gap : rect.bottom + gap;
      const arrowLeft = Math.max(
        16,
        Math.min(targetCenterX - left, cardWidth - 16),
      );
      setPosition({ left, top, arrowLeft, side });
    };

    const scheduleUpdate = () => {
      cancelAnimationFrame(rafId);
      rafId = requestAnimationFrame(updatePosition);
    };

    scheduleUpdate();
    window.addEventListener("resize", scheduleUpdate);
    window.addEventListener("scroll", scheduleUpdate, true);

    const target = document.querySelector(targetSelector) as HTMLElement | null;
    if (target) {
      resizeObserver = new ResizeObserver(scheduleUpdate);
      resizeObserver.observe(target);
    }

    return () => {
      cancelAnimationFrame(rafId);
      window.removeEventListener("resize", scheduleUpdate);
      window.removeEventListener("scroll", scheduleUpdate, true);
      resizeObserver?.disconnect();
    };
  }, [targetSelector]);

  return (
    <div
      ref={cardRef}
      className="fixed z-[9999] w-[360px] max-w-[calc(100vw-1rem)] animate-in fade-in zoom-in-95 duration-200"
      style={{
        left: position?.left ?? 0,
        top: position?.top ?? 0,
        visibility: position ? "visible" : "hidden",
      }}
    >
      <div className="relative bg-card border border-border rounded-xl shadow-lg p-4">
        {position && (
          <div
            className="absolute size-3 bg-card border-border rotate-45"
            style={
              position.side === "top" || position.side === "bottom"
                ? {
                    left: (position.arrowLeft ?? 20) - 6,
                    top: position.side === "top" ? "calc(100% - 6px)" : "-6px",
                    borderLeftWidth: position.side === "top" ? "1px" : "0",
                    borderTopWidth: position.side === "top" ? "0" : "1px",
                    borderRightWidth: "1px",
                    borderBottomWidth: "1px",
                    borderStyle: "solid",
                  }
                : {
                    left:
                      position.side === "left" ? "calc(100% - 6px)" : "-6px",
                    top: (position.arrowTop ?? 20) - 6,
                    borderWidth: "1px",
                    borderStyle: "solid",
                  }
            }
          />
        )}
        <div className="flex items-start gap-3">
          <div className="flex-shrink-0 text-primary mt-0.5">{icon}</div>
          <div className="min-w-0 flex-1">
            <h4 className="text-sm font-semibold mb-1">{title}</h4>
            <p className="text-xs text-muted-foreground leading-relaxed">
              {description}
            </p>
          </div>
          <button
            onClick={onDismiss}
            className="text-muted-foreground hover:text-foreground transition-colors flex-shrink-0 cursor-pointer"
          >
            <X className="size-4" />
          </button>
        </div>
        <div className="mt-3 flex justify-end">
          <Button
            size="sm"
            variant="ghost"
            className="text-xs h-7"
            onClick={onDismiss}
          >
            Понятно
          </Button>
        </div>
      </div>
    </div>
  );
};

// ── Main component ──────────────────────────────────────────────────────────

const JOYRIDE_OPTIONS = {
  overlayClickAction: false as const,
  dismissKeyAction: false as const,
  blockTargetInteraction: false,
  skipScroll: true,
  skipBeacon: true,
  overlayColor: "rgba(0, 0, 0, 0.5)",
  zIndex: 11000,
  targetWaitTimeout: 2000,
};

const FunctionalityOnboarding: React.FC = () => {
  const location = useLocation();
  const { settings, setSettings } = useSettings();
  const { isTipComplete, markTipComplete, tourActive, setTourActive } =
    useFunctionalityOnboarding();

  const isChatRoute =
    location.pathname === "/" || location.pathname.startsWith("/threads/");

  // ── Startup tour ────────────────────────────────────────────────────────

  const [startupRun, setStartupRun] = useState(false);
  const [startupStep, setStartupStep] = useState(0);
  const startupStepRef = useRef(0);
  startupStepRef.current = startupStep;

  useEffect(() => {
    if (
      isChatRoute &&
      isOnboardingComplete() &&
      !isTipComplete(TIP_IDS.STARTUP_TOUR)
    ) {
      const timer = setTimeout(() => {
        setStartupRun(true);
        setTourActive(true);
      }, 600);
      return () => clearTimeout(timer);
    }
  }, [isChatRoute, isTipComplete, setTourActive]);

  useEffect(() => {
    const handler = () => {
      if (
        isChatRoute &&
        isOnboardingComplete() &&
        !isTipComplete(TIP_IDS.STARTUP_TOUR)
      ) {
        setTimeout(() => {
          setStartupRun(true);
          setTourActive(true);
        }, 600);
      }
    };
    window.addEventListener("setup-state-change", handler);
    return () => window.removeEventListener("setup-state-change", handler);
  }, [isChatRoute, isTipComplete, setTourActive]);

  useEffect(() => {
    if (!isChatRoute && startupRun) {
      setStartupRun(false);
      setTourActive(false);
    }
  }, [isChatRoute, startupRun, setTourActive]);

  const finishStartup = useCallback(() => {
    markTipComplete(TIP_IDS.STARTUP_TOUR);
    setStartupRun(false);
    setStartupStep(0);
    setTourActive(false);
  }, [markTipComplete, setTourActive]);

  const advanceStartup = useCallback(
    (_from: number, to: number) => {
      if (to === SIDEBAR_STEP_INDEX && !settings.sideBarOpen) {
        setSettings((prev) => ({ ...prev, sideBarOpen: true }));
      }
      setStartupStep(to);
    },
    [settings.sideBarOpen, setSettings],
  );

  const handleStartupEvent = useCallback(
    (data: EventData) => {
      const { type, action, status, index } = data;
      if (status === STATUS.FINISHED || status === STATUS.SKIPPED) {
        finishStartup();
        return;
      }
      if (type === EVENTS.STEP_AFTER) {
        if (action === ACTIONS.CLOSE || action === ACTIONS.SKIP) {
          finishStartup();
          return;
        }
        const next = action === ACTIONS.PREV ? index - 1 : index + 1;
        if (next < 0 || next >= STARTUP_STEPS.length) {
          finishStartup();
          return;
        }
        advanceStartup(index, next);
      }
    },
    [finishStartup, advanceStartup],
  );

  // ── Keyboard navigation (shared) ───────────────────────────────────────

  useEffect(() => {
    if (!startupRun) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (startupRun) finishStartup();
        return;
      }

      const target = e.target as HTMLElement;
      if (target.tagName === "TEXTAREA" || target.tagName === "INPUT") return;

      if (e.key === "ArrowRight" || e.key === "Enter") {
        e.preventDefault();
        if (startupRun) {
          const cur = startupStepRef.current;
          if (cur >= STARTUP_STEPS.length - 1) {
            finishStartup();
            return;
          }
          advanceStartup(cur, cur + 1);
        }
      }

      if (e.key === "ArrowLeft") {
        e.preventDefault();
        if (startupRun) {
          const cur = startupStepRef.current;
          if (cur > 0) advanceStartup(cur, cur - 1);
        }
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [startupRun, finishStartup, advanceStartup]);

  // ── Runtime tips (detected via DOM observation) ─────────────────────────

  const watchAttachments =
    isChatRoute && !tourActive && !isTipComplete(TIP_IDS.ATTACHMENT_SELECTION);
  const attachmentPresent = useElementPresent(
    watchAttachments ? '[aria-label="select-attachment"]' : null,
  );

  const showAttachmentTip = attachmentPresent && watchAttachments;

  // ── Render ──────────────────────────────────────────────────────────────

  return (
    <>
      {startupRun && (
        <Joyride
          continuous
          run={startupRun}
          stepIndex={startupStep}
          steps={STARTUP_STEPS}
          onEvent={handleStartupEvent}
          tooltipComponent={CustomTooltip}
          options={JOYRIDE_OPTIONS}
        />
      )}

      {showAttachmentTip && (
        <RuntimeTip
          title="Выбор вложений из ответа"
          description="Когда агент генерирует изображения или графики, вы можете выбрать их (кликнув на чекбокс) и отправить обратно как контекст для следующего сообщения."
          icon={<Check className="size-5" />}
          targetSelector='[data-onboarding="response-attachment-selector"], [aria-label="select-attachment"]'
          preferredSide="left"
          onDismiss={() => markTipComplete(TIP_IDS.ATTACHMENT_SELECTION)}
        />
      )}
    </>
  );
};

export default FunctionalityOnboarding;
