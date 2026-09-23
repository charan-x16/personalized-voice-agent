import { NextResponse } from "next/server";

import { parseCustomerDetail } from "@/lib/api-validation";
import {
  backendErrorResponse,
  bffErrorResponse,
  rejectCrossOriginMutation,
  unavailableResponse,
} from "@/lib/bff";
import { getSessionToken, requestBackend } from "@/lib/server-api";

const SAFE_CUSTOMER_ID = /^[a-zA-Z0-9_-]{1,64}$/;
const ACCESS_ACTIONS = new Set(["invitation", "revoke"]);

export async function POST(
  request: Request,
  context: { params: Promise<{ id: string; action: string }> },
) {
  const crossOriginResponse = rejectCrossOriginMutation(request);
  if (crossOriginResponse) return crossOriginResponse;

  const token = await getSessionToken();
  if (!token) return bffErrorResponse("Authentication required.", 401);

  const { id, action } = await context.params;
  if (!SAFE_CUSTOMER_ID.test(id) || !ACCESS_ACTIONS.has(action)) {
    return bffErrorResponse("Invalid customer access action.", 400);
  }

  let upstream: Response;
  try {
    upstream = await requestBackend(
      `/v1/customers/${encodeURIComponent(id)}/access/${action}`,
      { method: "POST", token },
    );
  } catch {
    return unavailableResponse();
  }
  if (!upstream.ok) return backendErrorResponse(upstream);

  try {
    const customer = parseCustomerDetail(await upstream.json());
    if (!customer || customer.id !== id) {
      return bffErrorResponse("Invalid customer-service response.", 502);
    }
    const response = NextResponse.json(customer);
    response.headers.set("Cache-Control", "no-store");
    const retryAfter = upstream.headers.get("retry-after");
    if (retryAfter) response.headers.set("Retry-After", retryAfter);
    return response;
  } catch {
    return bffErrorResponse("Invalid customer-service response.", 502);
  }
}
