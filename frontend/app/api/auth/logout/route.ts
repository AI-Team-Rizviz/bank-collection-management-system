import { NextRequest } from "next/server";
import { TOKEN_COOKIE } from "@/lib/auth/server";

export async function POST(request: NextRequest) {
  if (request.headers.get("origin") !== request.nextUrl.origin)
    return Response.json({ message: "Same-origin request required" }, { status: 403 });
  const response = Response.json({ ok: true });
  response.headers.append(
    "Set-Cookie",
    `${TOKEN_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0`,
  );
  return response;
}
