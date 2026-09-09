import "server-only";

import { auth } from "@clerk/nextjs/server";

import type {
  ConversationDetailResponse,
  ConversationListResponse,
  CustomerDetail,
  CustomerListQuery,
  CustomerListResponse,
  MeResponse,
} from "@/lib/api-types";
import {
  parseConversationDetailResponse,
  parseConversationListResponse,
  parseCustomerDetail,
  parseCustomerListResponse,
  parseCustomerListSearchParams,
  parseMeResponse,
} from "@/lib/api-validation";
const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";
const BACKEND_TIMEOUT_MS = 12_000;

export class BackendApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "BackendApiError";
    this.status = status;
  }
}

const SAFE_CUSTOMER_ID = /^[a-zA-Z0-9_-]{1,64}$/;

function customerListPath(options: CustomerListQuery): string {
  const candidate = new URLSearchParams();
  if (options.query !== undefined) {
    if (typeof options.query !== "string") {
      throw new BackendApiError("Invalid customer-list query.", 400);
    }
    candidate.set("query", options.query);
  }
  if (options.status !== undefined) candidate.set("status", String(options.status));
  if (options.limit !== undefined) candidate.set("limit", String(options.limit));
  if (options.offset !== undefined) candidate.set("offset", String(options.offset));

  const parsed = parseCustomerListSearchParams(candidate);
  if (!parsed) throw new BackendApiError("Invalid customer-list query.", 400);

  const canonical = new URLSearchParams();
  if (parsed.query !== undefined) canonical.set("query", parsed.query);
  if (parsed.status !== undefined) canonical.set("status", parsed.status);
  if (parsed.limit !== undefined) canonical.set("limit", String(parsed.limit));
  if (parsed.offset !== undefined) canonical.set("offset", String(parsed.offset));
  const queryString = canonical.toString();
  return queryString ? `/v1/customers?${queryString}` : "/v1/customers";
}

function apiUrl(path: string): URL {
  const configuredBase = process.env.API_BASE_URL?.trim() || DEFAULT_API_BASE_URL;
  const base = new URL(configuredBase.endsWith("/") ? configuredBase : `${configuredBase}/`);

  if (base.username || base.password) {
    throw new Error("API_BASE_URL must not contain embedded credentials.");
  }
  if (base.protocol !== "http:" && base.protocol !== "https:") {
    throw new Error("API_BASE_URL must use HTTP or HTTPS.");
  }
  if (base.search || base.hash) {
    throw new Error("API_BASE_URL must not contain a query string or fragment.");
  }

  const production = process.env.NODE_ENV === "production" || process.env.APP_ENV === "production";
  const loopback = base.hostname === "localhost" || base.hostname === "127.0.0.1" || base.hostname === "[::1]";
  if (production && base.protocol !== "https:" && !loopback) {
    throw new Error("Production API_BASE_URL must use HTTPS outside loopback.");
  }

  return new URL(path.replace(/^\//, ""), base);
}

export async function requestBackend(
  path: string,
  init: RequestInit & { token?: string } = {},
): Promise<Response> {
  const { token, ...requestInit } = init;
  const headers = new Headers(requestInit.headers);
  headers.set("Accept", "application/json");
  headers.delete("cookie");

  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  } else {
    headers.delete("Authorization");
  }

  return fetch(apiUrl(path), {
    ...requestInit,
    headers,
    cache: "no-store",
    signal: requestInit.signal ?? AbortSignal.timeout(BACKEND_TIMEOUT_MS),
  });
}

export async function getSessionToken(): Promise<string | null> {
  const { getToken } = await auth();
  return getToken();
}

async function readErrorDetail(response: Response): Promise<string> {
  try {
    const payload: unknown = await response.json();
    if (
      typeof payload === "object" &&
      payload !== null &&
      "detail" in payload &&
      typeof payload.detail === "string"
    ) {
      return payload.detail;
    }
  } catch {
    // The backend can return an empty or non-JSON error response.
  }

  return "The application service could not complete this request.";
}

async function authenticatedJson<T>(
  path: string,
  parse: (value: unknown) => T | null,
): Promise<T | null> {
  const token = await getSessionToken();
  if (!token) return null;

  let response: Response;
  try {
    response = await requestBackend(path, { token });
  } catch {
    throw new BackendApiError("The application service is unavailable.", 503);
  }

  if (response.status === 401) return null;
  if (!response.ok) {
    throw new BackendApiError(await readErrorDetail(response), response.status);
  }

  try {
    const parsed = parse(await response.json());
    if (!parsed) {
      throw new BackendApiError("The application service returned an invalid response.", 502);
    }
    return parsed;
  } catch {
    throw new BackendApiError("The application service returned an invalid response.", 502);
  }
}

export function getCurrentProfile(): Promise<MeResponse | null> {
  return authenticatedJson<MeResponse>("/v1/me", parseMeResponse);
}

export async function getConversations(options: { query?: string; outcome?: string; page?: number } = {}): Promise<ConversationListResponse | null> {
  const params = new URLSearchParams();
  if (options.query) params.set("query", options.query);
  if (options.outcome) params.set("outcome", options.outcome);
  if (options.page !== undefined) {
    params.set("limit", "20");
    params.set("offset", String((options.page - 1) * 20));
  }
  return authenticatedJson<ConversationListResponse>(
    `/v1/conversations?${params}`,
    parseConversationListResponse,
  );
}

export async function getConversation(
  id: string,
): Promise<ConversationDetailResponse | null> {
  return authenticatedJson<ConversationDetailResponse>(
    `/v1/conversations/${encodeURIComponent(id)}`,
    parseConversationDetailResponse,
  );
}

export function getCustomers(
  options: CustomerListQuery = {},
): Promise<CustomerListResponse | null> {
  return authenticatedJson<CustomerListResponse>(
    customerListPath(options),
    parseCustomerListResponse,
  );
}

export async function getCustomer(id: string): Promise<CustomerDetail | null> {
  if (!SAFE_CUSTOMER_ID.test(id)) {
    throw new BackendApiError("Invalid customer identifier.", 400);
  }

  const customer = await authenticatedJson<CustomerDetail>(
    `/v1/customers/${encodeURIComponent(id)}`,
    parseCustomerDetail,
  );
  if (customer !== null && customer.id !== id) {
    throw new BackendApiError("The application service returned an invalid response.", 502);
  }
  return customer;
}
