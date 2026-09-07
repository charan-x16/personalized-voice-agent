import { NextResponse } from "next/server";

import {
  backendErrorResponse,
  bffErrorResponse,
  BffInputError,
  readJsonObject,
  rejectCrossOriginMutation,
  rejectNonJsonRequest,
  unavailableResponse,
} from "@/lib/bff";
import { requestBackend, SESSION_COOKIE_NAME } from "@/lib/server-api";

const MAX_LOGIN_BYTES = 4 * 1024;
const DEMO_ACCOUNTS = new Set([
  "rahul@example.com",
  "ananya@acme.example",
]);

type TokenResponse = {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
};

function isTokenResponse(value: unknown): value is TokenResponse {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Partial<TokenResponse>;
  return (
    typeof candidate.access_token === "string" &&
    candidate.access_token.length > 0 &&
    candidate.access_token.length <= 4_096 &&
    candidate.token_type === "bearer" &&
    typeof candidate.expires_in === "number" &&
    Number.isInteger(candidate.expires_in) &&
    candidate.expires_in > 0
  );
}

export async function POST(request: Request) {
  const crossOriginResponse = rejectCrossOriginMutation(request);
  if (crossOriginResponse) return crossOriginResponse;
  const mediaTypeResponse = rejectNonJsonRequest(request);
  if (mediaTypeResponse) return mediaTypeResponse;

  let body: Record<string, unknown>;
  try {
    body = await readJsonObject(request, MAX_LOGIN_BYTES);
  } catch (error) {
    if (error instanceof BffInputError) {
      return bffErrorResponse(error.message, error.status);
    }
    return bffErrorResponse("Invalid request.", 400);
  }

  const normalizedEmail =
    typeof body.email === "string" ? body.email.trim().toLowerCase() : "";
  if (
    Object.keys(body).some((key) => key !== "email") ||
    !DEMO_ACCOUNTS.has(normalizedEmail)
  ) {
    return bffErrorResponse("Invalid demo account.", 400);
  }

  let upstream: Response;
  try {
    upstream = await requestBackend("/v1/auth/demo-login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: normalizedEmail }),
    });
  } catch {
    return unavailableResponse();
  }

  if (!upstream.ok) return backendErrorResponse(upstream);

  let token: unknown;
  try {
    token = await upstream.json();
  } catch {
    return bffErrorResponse("Invalid authentication response.", 502);
  }

  if (!isTokenResponse(token)) {
    return bffErrorResponse("Invalid authentication response.", 502);
  }

  const response = NextResponse.json({ ok: true });
  response.headers.set("Cache-Control", "no-store");
  response.cookies.set({
    name: SESSION_COOKIE_NAME,
    value: token.access_token,
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: Math.min(Math.floor(token.expires_in), 24 * 60 * 60),
  });
  return response;
}
