// ThinkingIndicator.tsx
import React, { useEffect, useRef, useState } from "react";
import { Message as Message_ } from "@langchain/langgraph-sdk";
import type { UseStream } from "@langchain/langgraph-sdk/react";
import { GraphState } from "../interfaces.ts";
import { useExperimentalMode } from "@/hooks/useExperimentalMode.ts";
import { useActivityPanel } from "./experimental/ActivityPanelProvider";

interface ThinkingProps {
  messages: Message_[];
  thread?: UseStream<GraphState>;
  threadId?: string;
}

// Скорость «печати» нового куска статуса, мс на символ.
const TYPE_MS = 18;

// В экспериментальном режиме бэк пушит статус того, что делает агент, через
// push_ui_message("experimental_status", { text }). Достаём последний такой
// статус из thread.values.ui.
function readExperimentalStatus(thread?: UseStream<GraphState>): string | null {
  const ui = (thread?.values as any)?.ui as any[] | undefined;
  if (!Array.isArray(ui)) {
    return null;
  }
  for (let i = ui.length - 1; i >= 0; i--) {
    if (ui[i]?.name === "experimental_status") {
      const text = ui[i]?.props?.text;
      return typeof text === "string" && text.trim() ? text : null;
    }
  }
  return null;
}

function commonPrefixLen(a: string, b: string): number {
  const min = Math.min(a.length, b.length);
  let i = 0;
  while (i < min && a[i] === b[i]) i++;
  return i;
}

const ThinkingIndicator = ({ messages, thread, threadId }: ThinkingProps) => {
  const { openForThread, close, isOpen } = useActivityPanel();
  const { experimentalActive } = useExperimentalMode();
  const isLoading = !!thread?.isLoading;
  const lastIsAi =
    messages.length > 0 && messages[messages.length - 1].type === "ai";
  // Экспериментальный режим: показываем строку статуса весь ран. Обычный:
  // прячем, как только пришло AI-сообщение (прежнее поведение).
  const active =
    isLoading && (experimentalActive || (messages.length > 0 && !lastIsAi));

  const status = experimentalActive ? readExperimentalStatus(thread) : null;
  const target = status || "Думаю…";

  // «Печатная машинка» только для экспериментальных статусов: при новом статусе
  // дописываем/переписываем ТОЛЬКО с места, где он разошёлся с предыдущим; если
  // статус не изменился — ничего не перепечатываем.
  const [displayed, setDisplayed] = useState("");
  const prevTargetRef = useRef("");
  const timerRef = useRef<number | null>(null);

  const clearTimer = () => {
    if (timerRef.current !== null) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
  };

  useEffect(() => {
    if (!experimentalActive) return;
    if (!active) {
      // Сброс между ранами, чтобы следующий статус печатался с нуля.
      clearTimer();
      prevTargetRef.current = "";
      setDisplayed("");
      return;
    }
    const prev = prevTargetRef.current;
    if (target === prev) return; // не изменился — не перепечатываем

    const start = commonPrefixLen(prev, target); // общий префикс сохраняем
    prevTargetRef.current = target;
    clearTimer();

    let n = start;
    setDisplayed(target.slice(0, n));
    if (n >= target.length) return;
    timerRef.current = window.setInterval(() => {
      n += 1;
      setDisplayed(target.slice(0, n));
      if (n >= target.length) clearTimer();
    }, TYPE_MS);
  }, [target, active, experimentalActive]);

  useEffect(() => () => clearTimer(), []);

  if (!active) return null;

  const text = experimentalActive ? displayed : "Думаю…";

  // В экспериментальном режиме клик по статусу открывает панель активности
  // (живой список действий текущего рана тянется из кэша по threadId).
  const clickable = experimentalActive && !!threadId;

  return (
    <div
      role={clickable ? "button" : undefined}
      title={clickable ? "Показать активность" : undefined}
      onClick={
        clickable
          ? () => (isOpen ? close() : openForThread(threadId!))
          : undefined
      }
      className={[
        "px-[34px] py-[10px] text-transparent bg-gradient-to-r from-foreground/40 via-foreground to-foreground/40 bg-clip-text animate-pulse",
        clickable ? "cursor-pointer" : "",
      ].join(" ")}
    >
      {text}
    </div>
  );
};

export default ThinkingIndicator;
