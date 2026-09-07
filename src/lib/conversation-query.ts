export const CONVERSATION_PAGE_SIZE = 20;
export const MAX_CONVERSATION_PAGE = 501;

export function conversationPage(value: string | undefined): number | null {
  if (value === undefined) return 1;
  if (!/^[1-9]\d*$/.test(value)) return null;
  const page = Number(value);
  return Number.isSafeInteger(page) && page <= MAX_CONVERSATION_PAGE ? page : null;
}

export function conversationArchiveHref(query: string, outcome: string, page = 1) {
  const params = new URLSearchParams();
  if (query) params.set("query", query);
  if (outcome !== "all") params.set("outcome", outcome);
  if (page > 1) params.set("page", String(page));
  return params.size ? `/conversations?${params}` : "/conversations";
}
