// ThinkingIndicator.tsx
import { AlertTriangle, RefreshCw } from "lucide-react";
import { useEffect, useRef } from "react";
import type { UseStream } from "@langchain/langgraph-sdk/react";
import { GraphState } from "@/interfaces.ts";

interface ChatErrorProps {
  thread?: UseStream<GraphState>;
}

const ChatError = ({ thread }: ChatErrorProps) => {
  // Защита от двойного клика: submit асинхронный, между кликом и переходом
  // thread.isLoading в true есть окно, в котором кнопка ещё видна и повторные
  // клики успели бы запустить несколько ранов. Ref закрывает это окно, а когда
  // ран подхватился (isLoading) — снимаем защиту для будущих ретраев.
  const submittingRef = useRef(false);
  useEffect(() => {
    if (thread?.isLoading) {
      submittingRef.current = false;
    }
  }, [thread?.isLoading]);

  if (!thread?.error || thread.isLoading) {
    return null;
  }

  // Отмена рана кнопкой «Стоп» приходит error-эвентом UserInterrupt —
  // это не ошибка чата, баннер не показываем (как и telegram-канал).
  const errorText = String(thread.error);
  if (errorText.includes("CancelledError")) {
    return null;
  }

  // Превышен лимит активных тредов (409 от auth-хендлера langgraph_auth.py).
  // Ран не был создан, поэтому в чекпоинт ничего не попало, но последнее
  // human-сообщение всё ещё лежит в thread.messages (оптимистичное). Ретрай
  // переотправляет именно его как новый input — без резюма от чекпоинта.
  const lastMessage = (thread.messages ?? []).at(-1);
  const canRetryMessage = lastMessage?.type === "human";

  // Переотправка последнего сообщения как нового рана. Та же защита от двойного
  // клика, что и в handleRetry. Сообщение уже в thread.messages, поэтому id
  // фиксируем и НЕ добавляем вторую копию (иначе серверный эхо задвоил бы его).
  const handleRetryMessage = () => {
    if (submittingRef.current || !lastMessage) return;
    submittingRef.current = true;
    const id = lastMessage.id ?? crypto.randomUUID();
    const human = { ...lastMessage, id };
    void thread.submit(
      { messages: [human] },
      {
        optimisticValues(prev) {
          const msgs = prev.messages ?? [];
          return { ...prev, messages: [...msgs.slice(0, -1), human] };
        },
        streamMode: ["messages"],
        onDisconnect: "continue",
      },
    );
  };

  if (errorText.includes("TOO_MANY_ACTIVE_THREADS")) {
    return (
      <div className="px-[34px] py-[10px] animate-in fade-in slide-in-from-top-1">
        <div className="flex items-center gap-2 rounded-lg border border-destructive bg-destructive/20 px-[10px] py-[15px] text-destructive-foreground">
          <AlertTriangle size={18} className="shrink-0" />
          Слишком много активных чатов — дождитесь их завершения или остановите
          ненужные.
          {canRetryMessage && (
            <button
              type="button"
              aria-label="Отправить заново"
              onClick={handleRetryMessage}
              className="ml-auto shrink-0 cursor-pointer rounded-lg p-1.5 transition-colors hover:bg-destructive/40"
            >
              <RefreshCw size={16} />
            </button>
          )}
        </div>
      </div>
    );
  }

  const handleRetry = () => {
    if (submittingRef.current) return;
    submittingRef.current = true;
    // У нас fetchStateHistory: false, поэтому SDK не подставляет implicit-checkpoint
    // и submit(undefined) уходит без input/command/checkpoint. Реальный langgraph это
    // допускает (resume от последнего чекпоинта), а aegra отвечает 422
    // ("Must specify at least one of 'input', 'command', or 'checkpoint'").
    // Передаём checkpoint — aegra принимает его (это non-None dict) и, т.к.
    // input/command пустые, резюмит ран от последнего чекпоинта (pending tasks).
    // checkpoint_id/checkpoint_map = null отфильтровываются на бэке, остаётся
    // checkpoint_ns: "" — корневой неймспейс основного графа.
    void thread.submit(undefined, {
      checkpoint: {
        checkpoint_ns: "",
        checkpoint_id: null,
        checkpoint_map: null,
      },
    });
  };

  return (
    <div className="px-[34px] py-[10px] animate-in fade-in slide-in-from-top-1">
      <div className="flex items-center gap-2 rounded-lg border border-destructive bg-destructive/20 px-[10px] py-[15px] text-destructive-foreground">
        <AlertTriangle size={18} className="shrink-0" />В чате произошла ошибка
        <button
          type="button"
          aria-label="Повторить"
          onClick={handleRetry}
          className="ml-auto shrink-0 cursor-pointer rounded-lg p-1.5 transition-colors hover:bg-destructive/40"
        >
          <RefreshCw size={16} />
        </button>
      </div>
    </div>
  );
};

export default ChatError;
