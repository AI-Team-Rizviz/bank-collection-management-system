import { NextRequest } from "next/server";
import { TOKEN_COOKIE } from "@/lib/auth/server";

/**
 * Username/password sign-in. The credentials are forwarded to the IAM service
 * (POST /api/v1/auth/login), which verifies them and returns a signed access token.
 * The token is stored in an HttpOnly cookie and never exposed to browser JavaScript.
 */
export async function POST(request: NextRequest) {
  if (process.env.IAM_ADAPTER !== "live" || !process.env.IAM_API_BASE_URL)
    return Response.json({ message: "Sign-in is not available" }, { status: 404 });
  if (request.headers.get("origin") !== request.nextUrl.origin)
    return Response.json({ message: "Same-origin request required" }, { status: 403 });
  const { username, password } = (await request.json().catch(() => ({}))) as {
    username?: string;
    password?: string;
  };
  if (!username || !password)
    return Response.json({ message: "Enter your username and password" }, { status: 422 });
  let upstream: Response;
  try {
    upstream = await fetch(`${process.env.IAM_API_BASE_URL}/api/v1/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
      cache: "no-store",
      signal: AbortSignal.timeout(10000),
    });
  } catch {
    return Response.json({ message: "IAM service is unavailable" }, { status: 503 });
  }
  if (upstream.status === 401 || upstream.status === 422)
    return Response.json({ message: "Invalid username or password" }, { status: 401 });
  if (!upstream.ok)
    return Response.json({ message: "IAM service is unavailable" }, { status: 503 });
  const { access_token: token, expires_in: expiresIn } = (await upstream.json().catch(() => ({}))) as {
    access_token?: string;
    expires_in?: number;
  };
  if (!token) return Response.json({ message: "Sign-in failed" }, { status: 502 });
  const secure = process.env.NODE_ENV === "production" ? "; Secure" : "";
  const response = Response.json({ ok: true });
  response.headers.append(
    "Set-Cookie",
    `${TOKEN_COOKIE}=${token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=${expiresIn ?? 3600}${secure}`,
  );
  return response;
}
