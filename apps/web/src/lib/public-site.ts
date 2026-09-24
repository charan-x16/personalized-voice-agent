function safePublicUrl(value: string | undefined): URL | null {
  if (!value?.trim()) return null;

  try {
    const url = new URL(value.trim());
    if (url.protocol !== "https:" && url.protocol !== "http:") return null;
    if (url.username || url.password || url.search || url.hash) return null;
    return url;
  } catch {
    return null;
  }
}

function safeSupportDestination(value: string | undefined): string | null {
  if (!value?.trim() || /[\r\n]/u.test(value)) return null;

  try {
    const url = new URL(value.trim());
    if (url.protocol !== "https:" && url.protocol !== "mailto:") return null;
    return url.href;
  } catch {
    return null;
  }
}

export const PUBLIC_SITE_URL = safePublicUrl(process.env.NEXT_PUBLIC_SITE_URL);
export const PUBLIC_SUPPORT_DESTINATION = safeSupportDestination(
  process.env.NEXT_PUBLIC_SUPPORT_URL,
);
