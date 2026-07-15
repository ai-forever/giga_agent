import React, {
  useState,
  useCallback,
  useEffect,
  useRef,
  CSSProperties,
} from "react";
import {
  Joyride,
  ACTIONS,
  EVENTS,
  STATUS,
  Step,
  TooltipRenderProps,
  EventData,
  ArrowRenderProps,
} from "react-joyride";
import { useLocation } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { isOnboardingComplete } from "./OnboardingWizard";
import {
  useFunctionalityOnboarding,
  TIP_IDS,
} from "./FunctionalityOnboardingContext";
// ── Startup tour steps ──────────────────────────────────────────────────────

const STARTUP_STEPS: Step[] = [
  {
    target: '[data-onboarding="autonomy-switch"]',
    placement: "bottom",
    title: "Автономность",
    content:
      "Когда этот режим включён, агент автоматически подтверждает промежуточные действия без ожидания вашего ответа. Отключите, если хотите контролировать каждый шаг.",
    skipBeacon: true,
  },
  {
    target: '[data-onboarding="gear-menu-btn"]',
    placement: "right",
    title: "Меню настроек чата",
    content:
      "В этом меню находятся персонализация ответов, подключение инструментов (MCP) и выбор документов для RAG. Откройте его, чтобы познакомиться с каждой функцией.",
    skipBeacon: true,
    spotlightPadding: 2,
  },
];

// ── Shared tooltip ──────────────────────────────────────────────────────────

const CustomTooltip: React.FC<TooltipRenderProps> = ({
  index,
  isLastStep,
  size,
  step,
  skipProps,
  primaryProps,
  tooltipProps,
}) => {
  return (
    <div
      role={tooltipProps.role}
      aria-modal={tooltipProps["aria-modal"]}
      className="bg-card dark:bg-zinc-800 border border-border dark:border-highlight rounded-xl overflow-hidden w-[340px] max-w-[calc(100vw-1rem)]"
      style={{ position: "relative", zIndex: 8 }}
    >
      <div className="p-4">
        <div className="min-w-0 mb-1.5 flex items-start justify-between gap-2">
          {step.title ? (
            <h3 className="font-semibold text-sm leading-snug">
              {step.title as string}
            </h3>
          ) : (
            <div />
          )}
          {size > 1 && (
            <div className="text-xs text-muted-foreground shrink-0">
              {index + 1}/{size}
            </div>
          )}
        </div>
        <div className="min-w-0">
          <div className="text-xs text-muted-foreground leading-relaxed">
            {step.content}
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 mt-3 pt-3 border-t border-border">
          {!isLastStep && (
            <Button
              variant="ghost"
              size="sm"
              onClick={skipProps.onClick}
              className="h-8 text-xs text-muted-foreground"
            >
              Пропустить
            </Button>
          )}
          <Button
            size="sm"
            onClick={primaryProps.onClick}
            className="h-8 text-xs"
          >
            {isLastStep ? "Понятно" : "Дальше"}
          </Button>
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
  targetSelector: string;
  preferredSide?: "left" | "right" | "top" | "bottom";
  onDismiss: () => void;
}> = ({
  title,
  description,
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
  }, [targetSelector, preferredSide]);

  return (
    <div
      ref={cardRef}
      className="fixed z-[8] w-[320px] max-w-[calc(100vw-1rem)] animate-in fade-in zoom-in-95 duration-200"
      style={{
        left: position?.left ?? 0,
        top: position?.top ?? 0,
        visibility: position ? "visible" : "hidden",
      }}
    >
      <div className="relative bg-card dark:bg-zinc-800 border border-border rounded-xl shadow-xl p-4">
        {position && (
          <div
            className="absolute"
            style={
              position.side === "top" || position.side === "bottom"
                ? {
                    left: position.arrowLeft ? position.arrowLeft - 10 : 20,
                    top: position.side === "top" ? "calc(100%)" : "0px",
                    borderLeftWidth: position.side === "top" ? "1px" : "0",
                    borderTopWidth: position.side === "top" ? "0" : "1px",
                    borderRightWidth: "1px",
                    borderBottomWidth: "1px",
                    borderStyle: "solid",
                  }
                : {
                    left: position.side === "left" ? "calc(100%)" : "",
                    top: position.arrowTop
                      ? Math.max(15, position.arrowTop - 10)
                      : 20,
                    borderWidth: "1px",
                    borderStyle: "solid",
                  }
            }
          >
            <CustomArrow
              placement={position.side}
              size={16}
              base={32}
              disableDarkBorder={true}
            />
          </div>
        )}
        <div className="min-w-0 flex-1">
          <h4 className="text-sm font-semibold mb-1">{title}</h4>
          <p className="text-xs text-muted-foreground leading-relaxed">
            {description}
          </p>
        </div>
        <div className="mt-3 flex justify-end">
          <Button size="sm" className="h-8 text-xs" onClick={onDismiss}>
            Понятно
          </Button>
        </div>
      </div>
    </div>
  );
};

// ── Main component ──────────────────────────────────────────────────────────

const BORDER_WIDTH = 1;

interface ArrowProps extends ArrowRenderProps {
  disableDarkBorder?: boolean;
}

function CustomArrow({
  base,
  placement,
  size,
  disableDarkBorder = false,
}: ArrowProps) {
  let styles: CSSProperties = {};
  if (placement.startsWith("top")) {
    styles = {
      transform: "rotate(180deg)",
      top: "-1px",
    };
  } else if (placement.startsWith("bottom")) {
    styles = {
      bottom: "-1px",
    };
  } else if (placement.startsWith("right")) {
    styles = {
      transform: "rotate(270deg)",
      right: `-${size / 4 + 5}px`,
    };
  } else if (placement.startsWith("left")) {
    styles = {
      transform: "rotate(90deg)",
      left: `-${size / 4 + 5}px`,
    };
  }

  return (
    <div>
      <div
        className={`bg-border ${disableDarkBorder ? "dark:bg-zinc-800" : "dark:bg-highlight"}`}
        style={{
          ...styles,
          width: base,
          height: size,
          clipPath: `polygon(${size * 2}px ${size}px, ${size}px 0px, 0px ${size}px)`,
          position: "absolute",
          zIndex: "9",
        }}
      />
      <div
        className={"bg-card dark:bg-zinc-800"}
        style={{
          ...styles,
          width: base,
          height: size,
          clipPath: `polygon(${size * 2 - BORDER_WIDTH}px ${size}px, ${size}px ${BORDER_WIDTH}px, ${BORDER_WIDTH}px ${size}px)`,
          position: "absolute",
          zIndex: "9",
        }}
      />
    </div>
  );
}

const FunctionalityOnboarding: React.FC = () => {
  const location = useLocation();
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
      !isTipComplete(TIP_IDS.CHAT_FEATURE_TOUR)
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
        !isTipComplete(TIP_IDS.CHAT_FEATURE_TOUR)
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
    markTipComplete(TIP_IDS.CHAT_FEATURE_TOUR);
    setStartupRun(false);
    setStartupStep(0);
    setTourActive(false);
  }, [markTipComplete, setTourActive]);

  const advanceStartup = useCallback((_from: number, to: number) => {
    setStartupStep(to);
  }, []);

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
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [startupRun, finishStartup, advanceStartup]);

  // ── Runtime tips (detected via DOM observation) ─────────────────────────

  const watchAttachments =
    isChatRoute &&
    !tourActive &&
    !isTipComplete(TIP_IDS.RESPONSE_ATTACHMENT_TIP);
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
          arrowComponent={CustomArrow}
          onEvent={handleStartupEvent}
          tooltipComponent={CustomTooltip}
          loaderComponent={null}
          options={{
            overlayClickAction: false,
            dismissKeyAction: false,
            blockTargetInteraction: false,
            skipScroll: true,
            skipBeacon: true,
            overlayColor: "transparent",
            zIndex: 8,
            targetWaitTimeout: 2000,
            hideOverlay: true,
          }}
          styles={{
            floater: { filter: "none" },
            overlay: { zIndex: "8" },
          }}
        />
      )}

      {showAttachmentTip && (
        <RuntimeTip
          title="Выбор вложений из ответа"
          description="Когда агент генерирует изображения или графики, вы можете выбрать их (кликнув на чекбокс) и отправить обратно как контекст для следующего сообщения."
          targetSelector='[data-onboarding="response-attachment-selector"], [aria-label="select-attachment"]'
          preferredSide="left"
          onDismiss={() => markTipComplete(TIP_IDS.RESPONSE_ATTACHMENT_TIP)}
        />
      )}
    </>
  );
};

export default FunctionalityOnboarding;
