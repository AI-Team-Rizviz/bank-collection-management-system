import { it, expect, vi, beforeEach, afterEach } from "vitest";
import { NextRequest } from "next/server";
import { mockSession } from "@/mocks/fixtures";
import { MockIamService } from "@/mocks/service";
vi.mock("@/lib/auth/server", () => ({ getSession: vi.fn() }));
import { getSession } from "@/lib/auth/server";
import { GET, POST } from "@/app/api/v1/[...path]/route";
import { request } from "@/lib/api/client";
beforeEach(() => {
  vi.stubEnv("IAM_ADAPTER", "mock");
  vi.mocked(getSession).mockResolvedValue(mockSession);
  globalThis.__mockIam = new MockIamService();
});
afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});
const context = (path: string) => ({
  params: Promise.resolve({ path: path.split("/") }),
});
it("denies API access without a verified session", async () => {
  vi.mocked(getSession).mockResolvedValue(null);
  const r = await GET(
    new NextRequest("http://localhost/api/v1/users"),
    context("users"),
  );
  expect(r.status).toBe(401);
});
it("enforces read permissions at the same-origin boundary", async () => {
  vi.mocked(getSession).mockResolvedValue({ ...mockSession, permissions: [] });
  const r = await GET(
    new NextRequest("http://localhost/api/v1/users"),
    context("users"),
  );
  expect(r.status).toBe(403);
});
it("rejects cross-origin writes", async () => {
  const r = await POST(
    new NextRequest("http://localhost/api/v1/users", {
      method: "POST",
      headers: { origin: "https://other.example" },
      body: "{}",
    }),
    context("users"),
  );
  expect(r.status).toBe(403);
});
it("exposes a deterministic development failure for UI recovery", async () => {
  const r = await GET(
    new NextRequest("http://localhost/api/v1/users", {
      headers: { "x-mock-failure": "true" },
    }),
    context("users"),
  );
  expect(r.status).toBe(503);
  expect(await r.json()).toEqual({
    message: "Simulated IAM service interruption. Please retry.",
  });
});
it("normalizes live HTTP unauthorized responses to the same client error contract", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(
        Response.json({ message: "Session expired" }, { status: 401 }),
      ),
  );
  await expect(request("users")).rejects.toMatchObject({
    status: 401,
    message: "Session expired",
  });
});
it("normalizes network failures", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
  await expect(request("users")).rejects.toMatchObject({
    status: 0,
    message: expect.stringContaining("Check your connection"),
  });
});
it("sends query parameters, cancellation and same-origin credentials consistently", async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValue(
      Response.json({ items: [], total: 0, page: 2, pageSize: 8 }),
    );
  vi.stubGlobal("fetch", fetcher);
  const controller = new AbortController();
  await request("users", {
    params: { page: 2, search: "Fatima Khan" },
    signal: controller.signal,
  });
  expect(fetcher).toHaveBeenCalledWith(
    "/api/v1/users?page=2&search=Fatima+Khan",
    expect.objectContaining({
      credentials: "same-origin",
      signal: expect.any(AbortSignal),
    }),
  );
});

it("denies protected server-rendered pages without the required permission", async () => {
  const { Authorized } = await import("@/components/auth/authorized");
  const { render, screen } = await import("@testing-library/react");
  const { createElement } = await import("react");
  vi.mocked(getSession).mockResolvedValue({
    ...mockSession,
    permissions: ["iam.user.read"],
  });
  render(
    await Authorized({
      permission: "iam.role.read",
      children: createElement("p", null, "Restricted role content"),
    }),
  );
  expect(
    screen.getByRole("heading", { name: "Access restricted" }),
  ).toBeInTheDocument();
  expect(screen.queryByText("Restricted role content")).not.toBeInTheDocument();
});
