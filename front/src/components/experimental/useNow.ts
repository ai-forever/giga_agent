import { useEffect, useState } from "react";

/**
 * Текущее время в epoch-секундах, обновляется раз в секунду, ПОКА `active`.
 * Нужно для тикающего таймера «Работаю… mm:ss» активного рана.
 */
export function useNowSeconds(active: boolean): number {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    if (!active) return;
    setNow(Date.now() / 1000);
    const id = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => window.clearInterval(id);
  }, [active]);
  return now;
}
