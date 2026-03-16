type LogLevel = "error" | "warn" | "info" | "debug";

const levelOrder: Record<LogLevel, number> = {
  error: 0,
  warn: 1,
  info: 2,
  debug: 3,
};

function resolveLevel(): LogLevel {
  const raw = (import.meta.env.VITE_LOG_LEVEL ?? "").toLowerCase().trim();
  if (raw === "debug") return "debug";
  if (raw === "info") return "info";
  if (raw === "warn") return "warn";
  if (raw === "error") return "error";
  return import.meta.env.DEV ? "debug" : "info";
}

function shouldLog(current: LogLevel, level: LogLevel): boolean {
  return levelOrder[level] <= levelOrder[current];
}

function formatPrefix(level: LogLevel): string {
  const ts = new Date().toLocaleTimeString("en-US", { hour12: false });
  return `${ts} [mcp] ${level}:`;
}

export const logger = {
  get level(): LogLevel {
    return resolveLevel();
  },

  error(...args: unknown[]) {
    if (shouldLog(resolveLevel(), "error"))
      console.error(formatPrefix("error"), ...args);
  },
  warn(...args: unknown[]) {
    if (shouldLog(resolveLevel(), "warn"))
      console.warn(formatPrefix("warn"), ...args);
  },
  info(...args: unknown[]) {
    if (shouldLog(resolveLevel(), "info"))
      console.info(formatPrefix("info"), ...args);
  },
  debug(...args: unknown[]) {
    if (shouldLog(resolveLevel(), "debug"))
      console.debug(formatPrefix("debug"), ...args);
  },
};
