export const MAX_CONNECTION_EXPIRY_DELAY_MS = 65 * 60 * 1_000;

export function connectionExpiryDelayMilliseconds(
  expiresAt: string,
  now = Date.now(),
): number {
  const expiry = Date.parse(expiresAt);
  if (!Number.isFinite(expiry)) return 0;

  return Math.max(0, Math.min(expiry - now, MAX_CONNECTION_EXPIRY_DELAY_MS));
}
