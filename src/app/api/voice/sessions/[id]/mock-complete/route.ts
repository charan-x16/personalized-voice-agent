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
import { parseConversationDetailResponse } from "@/lib/api-validation";
import { getSessionToken, requestBackend } from "@/lib/server-api";

const SAFE_SESSION_ID = /^[a-zA-Z0-9_-]{1,100}$/;

export async function POST(
  request: Request,
  context: { params: Promise<{ id: string }> },
) {
  const crossOriginResponse = rejectCrossOriginMutation(request);
  if (crossOriginResponse) return crossOriginResponse;
  const mediaTypeResponse = rejectNonJsonRequest(request);
  if (mediaTypeResponse) return mediaTypeResponse;

  const mockEnabled =
    process.env.NODE_ENV !== "production" &&
    (process.env.VOICE_PROVIDER === undefined || process.env.VOICE_PROVIDER === "mock");
  if (!mockEnabled) {
    return bffErrorResponse("Not found.", 404);
  }

  const token = await getSessionToken();
  if (!token) {
    return bffErrorResponse("Authentication required.", 401);
  }

  const { id } = await context.params;
  if (!SAFE_SESSION_ID.test(id)) {
    return bffErrorResponse("Invalid session identifier.", 400);
  }

  let body: Record<string, unknown>;
  try {
    body = await readJsonObject(request);
  } catch (error) {
    if (error instanceof BffInputError) {
      return bffErrorResponse(error.message, error.status);
    }
    return bffErrorResponse("Invalid request.", 400);
  }

  let upstream: Response;
  try {
    upstream = await requestBackend(
      `/v1/voice/sessions/${encodeURIComponent(id)}/mock-complete`,
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
    const conversation = parseConversationDetailResponse(payload);
    if (!conversation) {
      return bffErrorResponse("Invalid voice-service response.", 502);
    }
    const response = NextResponse.json(conversation, { status: upstream.status });
    response.headers.set("Cache-Control", "no-store");
    return response;
  } catch {
    return bffErrorResponse("Invalid voice-service response.", 502);
  }
}
