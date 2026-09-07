import { NextResponse } from "next/server";

import {
  parseCustomerListResponse,
  parseCustomerListSearchParams,
} from "@/lib/api-validation";
import {
  backendErrorResponse,
  bffErrorResponse,
  unavailableResponse,
} from "@/lib/bff";
import { getSessionToken, requestBackend } from "@/lib/server-api";

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
