import "server-only";

import { NextResponse } from "next/server";

import { parseRetryAfterSeconds } from "@/lib/retry-after";

export const MAX_BFF_JSON_BYTES = 128 * 1024;

export function bffErrorResponse(
  detail: string,
  status: number,
  retryAfterSeconds?: number,
): NextResponse {
  const response = NextResponse.json({ detail }, { status });
  response.headers.set("Cache-Control", "no-store");
  if (retryAfterSeconds !== undefined) {
    response.headers.set(
      "Retry-After",
      String(Math.max(1, Math.min(Math.floor(retryAfterSeconds), 3_600))),
    );
  }
  return response;
}

export function rejectCrossOriginMutation(request: Request): NextResponse | null {
  const origin = request.headers.get("origin");
  const configuredOrigin = process.env.APP_ORIGIN?.trim();
  const expectedOrigin = configuredOrigin
    ? new URL(configuredOrigin).origin
    : new URL(request.url).origin;
  if (origin === expectedOrigin) return null;

  return bffErrorResponse("The request origin could not be verified.", 403);
}

export function rejectNonJsonRequest(request: Request): NextResponse | null {
  const mediaType = request.headers.get("content-type")?.split(";", 1)[0]?.trim().toLowerCase();
  if (mediaType === "application/json") return null;

  return bffErrorResponse("Content-Type must be application/json.", 415);
}

export async function readJsonObject(
  request: Request,
  maxBytes = MAX_BFF_JSON_BYTES,
): Promise<Record<string, unknown>> {
  const declaredLength = Number(request.headers.get("content-length"));
  if (Number.isFinite(declaredLength) && declaredLength > maxBytes) {
    throw new BffInputError("Request body is too large.", 413);
  }

  const reader = request.body?.getReader();
  const chunks: Uint8Array[] = [];
  let receivedBytes = 0;

  if (reader) {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      receivedBytes += value.byteLength;
      if (receivedBytes > maxBytes) {
        await reader.cancel();
        throw new BffInputError("Request body is too large.", 413);
      }
      chunks.push(value);
    }
  }

  const body = new Uint8Array(receivedBytes);
  let offset = 0;
  for (const chunk of chunks) {
    body.set(chunk, offset);
    offset += chunk.byteLength;
  }
  const text = new TextDecoder().decode(body);

  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    throw new BffInputError("A valid JSON object is required.", 400);
  }

  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new BffInputError("A valid JSON object is required.", 400);
  }

  return value as Record<string, unknown>;
}

export class BffInputError extends Error {
  readonly status: number;

  constructor(
    message: string,
    status: number,
  ) {
    super(message);
    this.name = "BffInputError";
    this.status = status;
  }
}

export async function backendErrorResponse(response: Response): Promise<NextResponse> {
  let detail = "The application service could not complete this request.";

  if (response.status < 500) {
    try {
      const payload: unknown = await response.json();
      if (
        typeof payload === "object" &&
        payload !== null &&
        "detail" in payload &&
        typeof payload.detail === "string"
      ) {
        detail = payload.detail;
      }
    } catch {
      // Keep the generic message for an empty or non-JSON upstream response.
    }
  }

  const status = response.status >= 400 && response.status <= 599 ? response.status : 502;
  const retryAfter = parseRetryAfterSeconds(response.headers.get("retry-after"));
  return bffErrorResponse(detail, status, retryAfter);
}

export function unavailableResponse(): NextResponse {
  return bffErrorResponse("The application service is temporarily unavailable.", 503, 3);
}
