/** Человекочитаемая длительность: «3.4s», «42s», «1m 9s». */
export function formatDuration(seconds: number): string {
  let s = seconds;
  if (!Number.isFinite(s) || s < 0) s = 0;
  if (s < 10) return `${s.toFixed(1)}s`;
  if (s < 60) return `${Math.round(s)}s`;
  const m = Math.floor(s / 60);
  const rem = Math.round(s % 60);
  return `${m}m ${rem}s`;
}
