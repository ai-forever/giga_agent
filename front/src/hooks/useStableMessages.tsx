import { useEffect, useRef, useState } from "react";

export function useStableMessages(thread: any) {
  const [stableMessages, setStableMessages] = useState(thread.messages ?? []);
  const previousMessagesRef = useRef(thread.messages ?? []);

  useEffect(() => {
    const next = thread.messages ?? [];
    if (next.length === 0) return;
    // Раньше тут стоял guard `!("__interrupt__" in thread.values)`, который
    // навсегда замораживал список, как только в ране случался interrupt
    // (ключ __interrupt__ держится в values до следующего submit). Из-за
    // этого ни токен-чанки после interrupt, ни финальный values с полной
    // перепиской не попадали в UI.
    //
    // Вместо этого просто не даём списку «схлопнуться»: при interrupt граф
    // коммитит состояние без недострименного сообщения и messages может стать
    // короче — такие регрессии игнорируем, а равные/растущие апдейты пускаем.
    if (next.length < previousMessagesRef.current.length) return;
    previousMessagesRef.current = next;
    setStableMessages(next);
    // @ts-ignore
    globalThis.messagesDebug = next;
  }, [thread.messages]);

  return stableMessages;
}
