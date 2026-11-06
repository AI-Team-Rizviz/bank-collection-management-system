import "server-only";
import { cookies } from "next/headers";
import { mockEnabled } from "./policy";
import type { Session } from "@/lib/api/types";

export const TOKEN_COOKIE = "iam_access_token";
export async function getSession(): Promise<Session | null> {
  if (mockEnabled())
    return (await import("@/mocks/service")).mockService().session();
  // Live sessions: the IAM service validates the bearer token and owns every decision.
  if (process.env.IAM_ADAPTER !== "live" || !process.env.IAM_API_BASE_URL)
    return null;
  const token = await getAccessToken();
  if (!token) return null;
  try {
    return await (await import("@/lib/iam/live")).liveSession(token);
  } catch {
    return null;
  }
}
export async function getAccessToken() {
  return (await cookies()).get(TOKEN_COOKIE)?.value ?? null;
}
