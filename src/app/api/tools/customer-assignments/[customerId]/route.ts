import { NextResponse } from "next/server";

import { parseCustomerVoiceToolListResponse } from "@/lib/api-validation";
import {
  backendErrorResponse,
  bffErrorResponse,
  unavailableResponse,
} from "@/lib/bff";
import { getSessionToken, requestBackend } from "@/lib/server-api";

const SAFE_ID = /^[a-zA-Z0-9_-]{1,64}$/;

export async function GET(
  _request: Request,
  context: { params: Promise<{ customerId: string }> },
) {
  const token = await getSessionToken();
  if (!token) return bffErrorResponse("Authentication required.", 401);
  const { customerId } = await context.params;
  if (!SAFE_ID.test(customerId)) return bffErrorResponse("Invalid customer identifier.", 400);

  let upstream: Response;
  try {
    upstream = await requestBackend(
      `/v1/tools/customer-assignments/${encodeURIComponent(customerId)}`,
      { token },
    );
  } catch {
    return unavailableResponse();
  }
  if (!upstream.ok) return backendErrorResponse(upstream);
  try {
    const tools = parseCustomerVoiceToolListResponse(await upstream.json());
    if (!tools || tools.customer_id !== customerId) {
      return bffErrorResponse("Invalid tool-service response.", 502);
    }
    const response = NextResponse.json(tools);
    response.headers.set("Cache-Control", "no-store");
    return response;
  } catch {
    return bffErrorResponse("Invalid tool-service response.", 502);
  }
}
