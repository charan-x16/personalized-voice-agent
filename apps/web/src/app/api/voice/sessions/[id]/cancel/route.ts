import { NextResponse } from "next/server";

import { parseCancelVoiceSessionResponse } from "@/lib/api-validation";
import {
  backendErrorResponse,
  bffErrorResponse,
  BffInputError,
  readJsonObject,
  rejectCrossOriginMutation,
  rejectNonJsonRequest,
  unavailableResponse,
} from "@/lib/bff";
import { getSessionToken, requestBackend } from "@/lib/server-api";

const SAFE_SESSION_ID = /^[a-zA-Z0-9_-]{1,100}$/;
const MAX_CANCEL_BYTES = 256;

export async function POST(
  request: Request,
  context: { params: Promise<{ id: string }> },
) {
  const crossOriginResponse = rejectCrossOriginMutation(request);
  if (crossOriginResponse) return crossOriginResponse;
  const mediaTypeResponse = rejectNonJsonRequest(request);
  if (mediaTypeResponse) return mediaTypeResponse;

  const token = await getSessionToken();
  if (!token) {
    return bffErrorResponse("Authentication required.", 401);
  }

  const { id } = await context.params;
  if (!SAFE_SESSION_ID.test(id)) {
    return bffErrorResponse("Invalid session identifier.", 400);
  }

  try {
    const body = await readJsonObject(request, MAX_CANCEL_BYTES);
    if (Object.keys(body).length) {
      return bffErrorResponse("Cancel request must be empty.", 400);
    }
  } catch (error) {
    if (error instanceof BffInputError) {
      return bffErrorResponse(error.message, error.status);
    }
    return bffErrorResponse("Invalid request.", 400);
  }

  let upstream: Response;
  try {
    upstream = await requestBackend(
      `/v1/voice/sessions/${encodeURIComponent(id)}/cancel`,
      {
        method: "POST",
        token,
        headers: { "Content-Type": "application/json" },
        body: "{}",
      },
    );
  } catch {
    return unavailableResponse();
  }

  if (!upstream.ok) return backendErrorResponse(upstream);

  try {
    const payload: unknown = await upstream.json();
    const cancellation = parseCancelVoiceSessionResponse(payload);
    if (!cancellation || cancellation.session_id !== id) {
      return bffErrorResponse("Invalid voice-service response.", 502);
    }
    const response = NextResponse.json(cancellation, { status: 200 });
    response.headers.set("Cache-Control", "no-store");
    return response;
  } catch {
    return bffErrorResponse("Invalid voice-service response.", 502);
  }
}
