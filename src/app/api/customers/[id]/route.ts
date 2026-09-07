import { NextResponse } from "next/server";

import {
  parseCustomerDetail,
  parseCustomerUpdatePayload,
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

const SAFE_CUSTOMER_ID = /^[a-zA-Z0-9_-]{1,64}$/;
const MAX_CUSTOMER_UPDATE_BYTES = 4 * 1024;

export async function GET(
  _request: Request,
  context: { params: Promise<{ id: string }> },
) {
  const token = await getSessionToken();
  if (!token) return bffErrorResponse("Authentication required.", 401);

  const { id } = await context.params;
  if (!SAFE_CUSTOMER_ID.test(id)) {
    return bffErrorResponse("Invalid customer identifier.", 400);
  }

  let upstream: Response;
  try {
    upstream = await requestBackend(`/v1/customers/${encodeURIComponent(id)}`, {
      token,
    });
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
    return response;
  } catch {
    return bffErrorResponse("Invalid customer-service response.", 502);
  }
}

export async function PATCH(
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
    body = await readJsonObject(request, MAX_CUSTOMER_UPDATE_BYTES);
  } catch (error) {
    if (error instanceof BffInputError) {
      return bffErrorResponse(error.message, error.status);
    }
    return bffErrorResponse("Invalid request.", 400);
  }

  const update = parseCustomerUpdatePayload(body);
  if (!update) {
    return bffErrorResponse(
      "Supply a valid expected revision, at least one customer field, and no unknown fields.",
      400,
    );
  }

  let upstream: Response;
  try {
    upstream = await requestBackend(`/v1/customers/${encodeURIComponent(id)}`, {
      method: "PATCH",
      token,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(update),
    });
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
    return response;
  } catch {
    return bffErrorResponse("Invalid customer-service response.", 502);
  }
}
