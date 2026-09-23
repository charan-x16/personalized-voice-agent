import { NextResponse } from "next/server";

import {
  parseCustomerCreatePayload,
  parseCustomerDetail,
  parseCustomerListResponse,
  parseCustomerListSearchParams,
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

const MAX_CUSTOMER_CREATE_BYTES = 8 * 1024;

export async function GET(request: Request) {
  const token = await getSessionToken();
  if (!token) return bffErrorResponse("Authentication required.", 401);

  const incoming = new URL(request.url).searchParams;
  const query = parseCustomerListSearchParams(incoming);
  if (!query) return bffErrorResponse("Invalid customer-list query.", 400);

  const upstreamParams = new URLSearchParams();
  if (query.query !== undefined) upstreamParams.set("query", query.query);
  if (query.status !== undefined) upstreamParams.set("status", query.status);
  if (query.limit !== undefined) upstreamParams.set("limit", String(query.limit));
  if (query.offset !== undefined) upstreamParams.set("offset", String(query.offset));
  const queryString = upstreamParams.toString();

  let upstream: Response;
  try {
    upstream = await requestBackend(
      queryString ? `/v1/customers?${queryString}` : "/v1/customers",
      { token },
    );
  } catch {
    return unavailableResponse();
  }

  if (!upstream.ok) return backendErrorResponse(upstream);

  try {
    const customers = parseCustomerListResponse(await upstream.json());
    if (!customers) return bffErrorResponse("Invalid customer-service response.", 502);

    const response = NextResponse.json(customers);
    response.headers.set("Cache-Control", "no-store");
    return response;
  } catch {
    return bffErrorResponse("Invalid customer-service response.", 502);
  }
}

export async function POST(request: Request) {
  const crossOriginResponse = rejectCrossOriginMutation(request);
  if (crossOriginResponse) return crossOriginResponse;
  const mediaTypeResponse = rejectNonJsonRequest(request);
  if (mediaTypeResponse) return mediaTypeResponse;

  const token = await getSessionToken();
  if (!token) return bffErrorResponse("Authentication required.", 401);

  let body: Record<string, unknown>;
  try {
    body = await readJsonObject(request, MAX_CUSTOMER_CREATE_BYTES);
  } catch (error) {
    if (error instanceof BffInputError) {
      return bffErrorResponse(error.message, error.status);
    }
    return bffErrorResponse("Invalid request.", 400);
  }

  const customerRequest = parseCustomerCreatePayload(body);
  if (!customerRequest) {
    return bffErrorResponse(
      "Supply a valid name, email, language, plan, optional reference, and no unknown fields.",
      400,
    );
  }

  let upstream: Response;
  try {
    upstream = await requestBackend("/v1/customers", {
      method: "POST",
      token,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(customerRequest),
    });
  } catch {
    return unavailableResponse();
  }
  if (!upstream.ok) return backendErrorResponse(upstream);

  try {
    const customer = parseCustomerDetail(await upstream.json());
    if (!customer) return bffErrorResponse("Invalid customer-service response.", 502);
    const response = NextResponse.json(customer, { status: 201 });
    response.headers.set("Cache-Control", "no-store");
    const retryAfter = upstream.headers.get("retry-after");
    if (retryAfter) response.headers.set("Retry-After", retryAfter);
    return response;
  } catch {
    return bffErrorResponse("Invalid customer-service response.", 502);
  }
}
