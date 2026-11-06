import { NextRequest } from "next/server";
import { TOKEN_COOKIE } from "@/lib/auth/server";

/**
 * DEVELOPMENT-ONLY sign-in. It mints a token from the local mock OIDC server for the
 * seeded user `demo-<username>` (see identity-access-service README, "Local development
 * login"). Disabled in production; replace with an authorization-code flow against the
 * bank's identity provider.
 */
export async function POST(request: NextRequest) {
  if (
    process.env.NODE_ENV === "production" ||
    process.env.IAM_DEV_LOGIN !== "true"
  )
    return Response.json({ message: "Dev sign-in is disabled" }, { status: 404 });
  if (request.headers.get("origin") !== request.nextUrl.origin)
    return Response.json({ message: "Same-origin request required" }, { status: 403 });
  const { username } = (await request.json().catch(() => ({}))) as {
    username?: string;
  };
  if (!username || !/^[a-z0-9][a-z0-9._-]{2,63}$/.test(username))
    return Response.json({ message: "Enter a valid username" }, { status: 422 });
  const tokenUrl =
    process.env.IAM_DEV_TOKEN_URL ?? "http://localhost:8081/default/token";
  let token: string | undefined;
  try {
    const response = await fetch(tokenUrl, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        grant_type: "client_credentials",
        client_id: `demo-${username}`,
        client_secret: "x",
        scope: process.env.IAM_DEV_AUDIENCE ?? "bank-cms-iam",
      }),
      signal: AbortSignal.timeout(10000),
    });
    token = (await response.json()).access_token;
  } catch {
    return Response.json(
      { message: "Identity provider is unreachable" },
      { status: 503 },
    );
  }
  if (!token)
    return Response.json({ message: "Sign-in failed" }, { status: 401 });
  // Verify IAM accepts this identity before issuing a session cookie.
  const check = await fetch(`${process.env.IAM_API_BASE_URL}/api/v1/me`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  }).catch(() => null);
  if (!check) return Response.json({ message: "IAM service is unavailable" }, { status: 503 });
  if (!check.ok)
    return Response.json(
      { message: "Access denied: no active IAM user for this account" },
      { status: 403 },
    );
  const response = Response.json({ ok: true });
  const exp = JSON.parse(
    Buffer.from(token.split(".")[1], "base64url").toString(),
  ).exp as number | undefined;
  const maxAge = exp ? Math.max(60, exp - Math.floor(Date.now() / 1000)) : 3600;
  response.headers.append(
    "Set-Cookie",
    `${TOKEN_COOKIE}=${token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=${maxAge}`,
  );
  return response;
}
