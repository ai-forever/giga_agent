import type { UseStream } from "@langchain/langgraph-sdk/react";

type AnyThread = UseStream<any, any> | null | undefined;
type ThreadHistory = NonNullable<UseStream<any, any>["history"]>;

/**
 * Безопасно читает thread.history. Геттер useStream бросает исключение,
 * если стрим создан с fetchStateHistory: false, поэтому при недоступной
 * локальной истории возвращаем пустой массив, а вызывающий код полагается
 * на запрос истории с сервера / на checkpoint из метаданных сообщения.
 */
export function safeThreadHistory(thread: AnyThread): ThreadHistory {
  try {
    return thread?.history ?? [];
  } catch {
    return [];
  }
}

// Геттеры useStream, которые бросают исключение при fetchStateHistory: false.
const THROWING_GETTERS = ["history", "experimental_branchTree"] as const;

/**
 * React 19 в dev-режиме логирует рендеры (logComponentRender →
 * addObjectDiffToProperties) и обходит пропсы через for..in, читая значение
 * каждого перечисляемого свойства. thread прокидывается пропсом во многие
 * компоненты, а его геттеры history/experimental_branchTree бросают
 * исключение при fetchStateHistory: false — из-за чего падает весь рендер.
 *
 * Делаем эти геттеры неперечисляемыми: for..in их пропускает, а прямой
 * доступ через safeThreadHistory продолжает работать. Идемпотентно, поэтому
 * безопасно вызывать на каждом рендере.
 */
export function hideThrowingThreadGetters<T extends AnyThread>(thread: T): T {
  if (!thread) return thread;
  for (const key of THROWING_GETTERS) {
    const desc = Object.getOwnPropertyDescriptor(thread, key);
    if (desc?.enumerable && desc.configurable) {
      Object.defineProperty(thread, key, { ...desc, enumerable: false });
    }
  }
  return thread;
}

/**
 * useStream фабрикует синтетический интеррапт `{ when: "breakpoint" }`, когда у
 * головного чекпоинта непустой `next`, но нет настоящего `__interrupt__` и стрим
 * не активен. При resume-загрузке треда в новой вкладке во время первого прогона
 * `getState` ловит состояние между узлами (next ещё непустой), а history.data в
 * join-пути не рефрешится (fetchStateHistory: false) — поэтому фантом «залипает».
 *
 * Граф использует только динамический `interrupt()` (всегда с `value`), статических
 * брейкпоинтов нет — значит интеррапт без `value` не требует ответа пользователя и
 * не должен включать UI «продолжить» (иначе уходит бессмысленный Command(resume)).
 * Отфильтровываем его в геттере `interrupts`; производный геттер `interrupt`
 * (читает `this.interrupts`) подхватывает фильтр автоматически. Идемпотентно.
 */
export function suppressPhantomBreakpointInterrupt<T extends AnyThread>(
  thread: T,
): T {
  if (!thread) return thread;
  const desc = Object.getOwnPropertyDescriptor(thread, "interrupts");
  const orig = desc?.get;
  if (!orig || !desc?.configurable) return thread;
  if ((orig as { __phantomFiltered?: boolean }).__phantomFiltered)
    return thread;

  const wrapped = function (this: unknown) {
    const all = (orig.call(this) ?? []) as Array<{
      when?: string;
      value?: unknown;
    }>;
    return all.filter(
      (it) => !(it && it.when === "breakpoint" && it.value === undefined),
    );
  };
  (wrapped as { __phantomFiltered?: boolean }).__phantomFiltered = true;
  Object.defineProperty(thread, "interrupts", { ...desc, get: wrapped });
  return thread;
}
