import "server-only";
import { cookies } from "next/headers";
import { z } from "zod";
import { mockEnabled } from "./policy";
import type { Session } from "@/lib/api/types";
export const sessionSchema = z.object({
  id: z.string(),
  name: z.string(),
  email: z.email(),
  role: z.string(),
  permissions: z.array(z.string()),
  regions: z.array(z.string()),
  mock: z.literal(false),
});
export async function getSession(): Promise<Session | null> {
  if (mockEnabled())
    return (await import("@/mocks/service")).mockService().session();
  // Live sessions are owned and verified by IAM. No browser tokens are accepted.
  if (process.env.IAM_ADAPTER !== "live" || !process.env.IAM_API_BASE_URL)
    return null;
  const cookieName = process.env.IAM_SESSION_COOKIE ?? "__Host-iam_session";
  const value = (await cookies()).get(cookieName)?.value;
  if (!value) return null;
  try {
    const response = await fetch(`${process.env.IAM_API_BASE_URL}/api/v1/me`, {
      headers: { Cookie: `${cookieName}=${encodeURIComponent(value)}` },
      cache: "no-store",
      signal: AbortSignal.timeout(10000),
    });
    if (!response.ok) return null;
    return sessionSchema.parse({ ...(await response.json()), mock: false });
  } catch {
    return null;
  }
}
