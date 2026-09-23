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
import { parseVoiceSessionResponse } from "@/lib/api-validation";
import { getSessionToken, requestBackend } from "@/lib/server-api";

const SAFE_CUSTOMER_ID = /^[a-zA-Z0-9_-]{1,64}$/;
const MAX_SESSION_BYTES = 4 * 1024;

export async function POST(
  request: Request,
  context: { params: Promise<{ id: string }> },
) {
  const crossOriginResponse = rejectCrossOriginMutation(request);
  if (crossOriginResponse) return crossOriginResponse;
  const mediaTypeResponse = rejectNonJsonRequest(request);
  if (mediaTypeResponse) return mediaTypeResponse;

  const token = await getSessionToken();
  if (!token) return bffErrorResponse("Authentication required.", 401);

  const { id } = await context.params;
  if (!SAFE_CUSTOMER_ID.test(id)) {
    return bffErrorResponse("Invalid customer identifier.", 400);
  }

  let body: Record<string, unknown>;
  try {
    body = await readJsonObject(request, MAX_SESSION_BYTES);
  } catch (error) {
    if (error instanceof BffInputError) {
      return bffErrorResponse(error.message, error.status);
    }
    return bffErrorResponse("Invalid request.", 400);
  }

  if (Object.keys(body).some((key) => key !== "language")) {
    return bffErrorResponse("Only language may be supplied.", 400);
  }
  if (body.language !== undefined && typeof body.language !== "string") {
    return bffErrorResponse("Language must be a string.", 400);
  }

  let upstream: Response;
  try {
    upstream = await requestBackend(
      `/v1/voice/customers/${encodeURIComponent(id)}/preview-sessions`,
      {
        method: "POST",
        token,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    );
  } catch {
    return unavailableResponse();
  }

  if (!upstream.ok) return backendErrorResponse(upstream);

  try {
    const payload: unknown = await upstream.json();
    const configuredWebsocketHosts = process.env.VOICE_WEBSOCKET_HOSTS
      ?.split(",")
      .map((host) => host.trim())
      .filter(Boolean);
    const backendHost = new URL(
      process.env.API_BASE_URL ?? "http://127.0.0.1:8000",
    ).hostname;
    const allowedWebsocketHosts = Array.from(
      new Set([
        ...(configuredWebsocketHosts ?? []),
        backendHost,
        ...(process.env.NODE_ENV === "production" ? [] : ["localhost", "127.0.0.1", "[::1]"]),
      ]),
    );
    const session = parseVoiceSessionResponse(payload, {
      allowedWebsocketHosts,
      requireWebsocketHostAllowlist: true,
    });
    if (!session) return bffErrorResponse("Invalid voice-service response.", 502);

    const response = NextResponse.json(session, { status: upstream.status });
    response.headers.set("Cache-Control", "no-store");
    return response;
  } catch {
    return bffErrorResponse("Invalid voice-service response.", 502);
  }
}
