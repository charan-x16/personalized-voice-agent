const MAX_RETRY_AFTER_SECONDS = 3_600;

export function parseRetryAfterSeconds(value: string | null): number | undefined {
  if (!value || !/^\d{1,6}$/.test(value)) return undefined;

  return Math.max(1, Math.min(Number(value), MAX_RETRY_AFTER_SECONDS));
}

export function boundedRetryAfterMilliseconds(
  value: string | null,
  defaultDelayMilliseconds: number,
  maximumDelayMilliseconds: number,
): number {
  const seconds = parseRetryAfterSeconds(value);
  if (seconds === undefined) return defaultDelayMilliseconds;

  return Math.min(seconds * 1_000, maximumDelayMilliseconds);
}
