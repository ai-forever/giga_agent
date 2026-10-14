import type { Client, Message } from "@langchain/langgraph-sdk";

const POLL_INTERVAL_MS = 300;
const CANCEL_WAIT_TIMEOUT_MS = 6000;

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

const hasPayload = (message: Message): boolean => {
  const content = message.content;
  const hasText =
    typeof content === "string"
      ? content.trim().length > 0
      : (content?.length ?? 0) > 0;
  const toolCalls = (message as { tool_calls?: unknown[] }).tool_calls ?? [];
  // Стоп во время рассуждений: content ещё пуст, но reasoning_content уже
  // настримлен и отображается — его тоже стоит сохранить.
  const reasoning = (
    message.additional_kwargs as Record<string, unknown> | undefined
  )?.reasoning_content;
  const hasReasoning =
    typeof reasoning === "string" && reasoning.trim().length > 0;
  return hasText || toolCalls.length > 0 || hasReasoning;
};

const hasPersistablePayload = (message: Message): boolean => {
  if (message.type === "ai") return hasPayload(message);
  return (
    message.type === "tool" &&
    Boolean(
      (message.additional_kwargs as Record<string, unknown> | undefined)
        ?.subagent_activity,
    )
  );
};

/**
 * Сохраняет частично настримленный AI-ответ и результаты отменённых суб-агентов
 * после thread.stop().
 *
 * Отмена рана убивает суперстеп ноды model до его завершения, поэтому
 * сообщение существует только в памяти вкладки. Ждём фактической отмены
 * рана и дописываем сообщение в чекпоинт через update_state
 * (as_node="model"), если его там ещё нет (стоп во время тула — есть).
 * Best effort: при таймауте отмены или активном ране ничего не пишем,
 * чтобы не вклиниться в чужой суперстеп.
 */
export async function persistStoppedMessages(
  client: Client,
  threadId: string,
  messagesToPersist: Message[],
): Promise<void> {
  const candidates = messagesToPersist.filter(
    (message) => Boolean(message.id) && hasPersistablePayload(message),
  );
  if (candidates.length === 0) return;
  try {
    const deadline = Date.now() + CANCEL_WAIT_TIMEOUT_MS;
    for (;;) {
      const runs = (await client.runs.list(threadId, { limit: 5 })) as Array<{
        status?: string;
      }>;
      const active = runs.some(
        (run) => run.status === "pending" || run.status === "running",
      );
      if (!active) break;
      if (Date.now() > deadline) return;
      await sleep(POLL_INTERVAL_MS);
    }

    const state = await client.threads.getState(threadId);
    const serverMessages =
      ((state.values as { messages?: Message[] })?.messages ?? []) || [];
    const existingToolCallIds = new Set(
      serverMessages
        .map((message) => (message as any).tool_call_id)
        .filter((id): id is string => typeof id === "string"),
    );
    const missing = candidates.filter(
      (message) =>
        !serverMessages.some((current) => current.id === message.id) &&
        !(
          typeof (message as any).tool_call_id === "string" &&
          existingToolCallIds.has((message as any).tool_call_id)
        ),
    );
    if (missing.length === 0) return;
    for (const message of missing) {
      if (message.type === "ai") {
        message.additional_kwargs = {
          ...message.additional_kwargs,
          rendered: true,
        };
      }
    }

    await client.threads.updateState(threadId, {
      values: { messages: missing },
      asNode: "model",
    });
  } catch {
    /* best effort — не мешаем пользователю продолжать */
  }
}

export async function persistStoppedAiMessage(
  client: Client,
  threadId: string,
  message: Message,
): Promise<void> {
  await persistStoppedMessages(client, threadId, [message]);
}
