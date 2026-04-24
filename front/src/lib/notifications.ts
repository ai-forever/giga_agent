const isBrowser = () =>
  typeof window !== "undefined" && "Notification" in window;

export async function ensureNotificationPermission(): Promise<boolean> {
  if (!isBrowser()) return false;
  if (Notification.permission === "granted") return true;
  if (Notification.permission === "denied") return false;
  try {
    const result = await Notification.requestPermission();
    return result === "granted";
  } catch {
    return false;
  }
}

export function notifyIfHidden(title: string, body?: string): void {
  if (!isBrowser()) return;
  if (Notification.permission !== "granted") return;
  if (!document.hidden) return;
  try {
    new Notification(title, { body, icon: "/favicon.ico" });
  } catch {
    // noop: некоторые браузеры кидают, если вкладка в фоне/без engagement
  }
}