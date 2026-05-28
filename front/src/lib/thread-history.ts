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
