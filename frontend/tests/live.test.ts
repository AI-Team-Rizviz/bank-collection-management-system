import { describe, expect, it, vi, beforeEach } from "vitest";
import { liveHandle, liveSession } from "@/lib/iam/live";

const now = "2026-01-01T00:00:00Z";
const routes: Record<string, unknown> = {
  "GET /api/v1/me": {
    user_id: "u1", username: "admin", display_name: "Admin One", status: "ACTIVE",
    roles: ["IAM_ADMIN"], scopes: [{ scope_type: "GLOBAL", scope_value: null }], authz_version: 1,
  },
  "GET /api/v1/me/permissions": { permissions: [{ code: "iam.user.read" }] },
  "GET /api/v1/users/u1": { id: "u1", email: "a@x.invalid" },
  "GET /api/v1/users": {
    items: [{ id: "u1", username: "admin", display_name: "Admin One", email: "a@x.invalid",
      external_identity_id: "demo-admin", status: "ACTIVE", created_at: now }], total: 1,
  },
  "GET /api/v1/roles": {
    items: [{ id: "r1", code: "IAM_ADMIN", name: "IAM Admin", description: null, status: "ACTIVE",
      is_system: true, is_privileged: true, phase: "MVP", created_at: now }], total: 1,
  },
  "GET /api/v1/teams": { items: [], total: 0 },
  "GET /api/v1/users/u1/roles": [{ status: "ACTIVE", role: { id: "r1" } }],
  "GET /api/v1/roles/r1/permissions": [{ code: "iam.user.read" }],
};
let calls: { key: string; auth: string | null; body?: string }[];
beforeEach(() => {
  calls = [];
  process.env.IAM_API_BASE_URL = "http://iam.test";
  vi.stubGlobal("fetch", async (url: string, init: RequestInit) => {
    const u = new URL(url);
    const key = `${init.method} ${u.pathname}`;
    calls.push({ key, auth: (init.headers as Record<string, string>).Authorization, body: init.body as string });
    if (!(key in routes)) return Response.json({ error: { message: "nope" } }, { status: 404 });
    return Response.json(routes[key]);
  });
});

describe("live IAM adapter", () => {
  it("maps /me to a session using the bearer token", async () => {
    const s = await liveSession("tok");
    expect(s).toMatchObject({ id: "u1", name: "Admin One", email: "a@x.invalid", permissions: ["iam.user.read"], mock: false });
    expect(calls.every((c) => c.auth === "Bearer tok")).toBe(true);
  });
  it("maps users with roles and paginates", async () => {
    const session = await liveSession("tok2");
    const page = (await liveHandle("GET", "users", session, "tok2", {}, {})) as { items: { roleIds: string[]; employeeReference: string }[]; total: number };
    expect(page.total).toBe(1);
    expect(page.items[0]).toMatchObject({ roleIds: ["r1"], employeeReference: "demo-admin" });
  });
  it("maps roles with permission codes and user counts", async () => {
    const session = await liveSession("tok3");
    const page = (await liveHandle("GET", "roles", session, "tok3", {}, {})) as { items: { permissions: string[]; userCount: number; privileged: boolean }[] };
    expect(page.items[0]).toMatchObject({ permissions: ["iam.user.read"], userCount: 1, privileged: true });
  });
  it("surfaces IAM errors with their status", async () => {
    const session = await liveSession("tok4");
    await expect(liveHandle("GET", "teams/zzz", session, "tok4", {}, {})).rejects.toMatchObject({ status: 404 });
  });
});
