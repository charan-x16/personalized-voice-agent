import { NextResponse } from "next/server";

import {
  parseVoiceToolCreatePayload,
  parseVoiceToolDefinitionResponse,
  parseVoiceToolListResponse,
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

const MAX_TOOL_BODY_BYTES = 8 * 1024;

export async function GET() {
  const token = await getSessionToken();
  if (!token) return bffErrorResponse("Authentication required.", 401);

  let upstream: Response;
  try {
    upstream = await requestBackend("/v1/tools", { token });
  } catch {
    return unavailableResponse();
  }
  if (!upstream.ok) return backendErrorResponse(upstream);

  try {
    const tools = parseVoiceToolListResponse(await upstream.json());
    if (!tools) return bffErrorResponse("Invalid tool-service response.", 502);
    const response = NextResponse.json(tools);
    response.headers.set("Cache-Control", "no-store");
    return response;
  } catch {
    return bffErrorResponse("Invalid tool-service response.", 502);
  }
}

export async function POST(request: Request) {
  const crossOrigin = rejectCrossOriginMutation(request);
  if (crossOrigin) return crossOrigin;
  const mediaType = rejectNonJsonRequest(request);
  if (mediaType) return mediaType;
  const token = await getSessionToken();
  if (!token) return bffErrorResponse("Authentication required.", 401);

  let body: Record<string, unknown>;
  try {
    body = await readJsonObject(request, MAX_TOOL_BODY_BYTES);
  } catch (error) {
    if (error instanceof BffInputError) return bffErrorResponse(error.message, error.status);
    return bffErrorResponse("Invalid request.", 400);
  }
  const payload = parseVoiceToolCreatePayload(body);
  if (!payload) {
    return bffErrorResponse("Supply a valid tool key, name, description, and capability.", 400);
  }

  let upstream: Response;
  try {
    upstream = await requestBackend("/v1/tools", {
      method: "POST",
      token,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch {
    return unavailableResponse();
  }
  if (!upstream.ok) return backendErrorResponse(upstream);

  try {
    const tool = parseVoiceToolDefinitionResponse(await upstream.json());
    if (!tool) return bffErrorResponse("Invalid tool-service response.", 502);
    const response = NextResponse.json(tool, { status: 201 });
    response.headers.set("Cache-Control", "no-store");
    return response;
  } catch {
    return bffErrorResponse("Invalid tool-service response.", 502);
  }
}
