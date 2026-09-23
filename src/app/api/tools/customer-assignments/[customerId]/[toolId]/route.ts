import { NextResponse } from "next/server";

import {
  parseCustomerVoiceToolResponse,
  parseCustomerVoiceToolUpdatePayload,
} from "@/lib/api-validation";
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

const SAFE_ID = /^[a-zA-Z0-9_-]{1,64}$/;

export async function PATCH(
  request: Request,
  context: { params: Promise<{ customerId: string; toolId: string }> },
) {
  const crossOrigin = rejectCrossOriginMutation(request);
  if (crossOrigin) return crossOrigin;
  const mediaType = rejectNonJsonRequest(request);
  if (mediaType) return mediaType;
  const token = await getSessionToken();
  if (!token) return bffErrorResponse("Authentication required.", 401);
  const { customerId, toolId } = await context.params;
  if (!SAFE_ID.test(customerId) || !SAFE_ID.test(toolId)) {
    return bffErrorResponse("Invalid customer or tool identifier.", 400);
  }

  let body: Record<string, unknown>;
  try {
    body = await readJsonObject(request, 2 * 1024);
  } catch (error) {
    if (error instanceof BffInputError) return bffErrorResponse(error.message, error.status);
    return bffErrorResponse("Invalid request.", 400);
  }
  const payload = parseCustomerVoiceToolUpdatePayload(body);
  if (!payload) return bffErrorResponse("Supply a valid assignment state and revision.", 400);

  let upstream: Response;
  try {
    upstream = await requestBackend(
      `/v1/tools/customer-assignments/${encodeURIComponent(customerId)}/${encodeURIComponent(toolId)}`,
      {
        method: "PATCH",
        token,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    );
  } catch {
    return unavailableResponse();
  }
  if (!upstream.ok) return backendErrorResponse(upstream);
  try {
    const assignment = parseCustomerVoiceToolResponse(await upstream.json());
    if (!assignment || assignment.tool.id !== toolId) {
      return bffErrorResponse("Invalid tool-service response.", 502);
    }
    const response = NextResponse.json(assignment);
    response.headers.set("Cache-Control", "no-store");
    return response;
  } catch {
    return bffErrorResponse("Invalid tool-service response.", 502);
  }
}
