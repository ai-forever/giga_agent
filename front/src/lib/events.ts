export const appEvents = new EventTarget();

export const THREADS_REFRESH_EVENT = "threads:refresh";

export const refreshThreads = () => {
  appEvents.dispatchEvent(new Event(THREADS_REFRESH_EVENT));
};
