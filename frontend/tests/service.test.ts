import { describe, it, expect, beforeEach } from "vitest";
import { MockIamService } from "@/mocks/service";
import { mockSession } from "@/mocks/fixtures";
import { mockEnabled } from "@/lib/auth/policy";
import type {
  AccessRequest,
  Page,
  User,
  Session,
  Dashboard,
  MutationResult,
} from "@/lib/api/types";
let service: MockIamService;
beforeEach(() => {
  service = new MockIamService();
});
const reviewer: Session = {
  ...mockSession,
  id: "USER-002",
  name: "Fatima Khan",
};
const user = {
  name: "Test Employee",
  username: "test.employee",
  email: "test.employee@example.test",
  employeeReference: "EMP-2000",
  roleId: "ROLE-1",
  teamId: "TEAM-001",
  scopeType: "OWN",
  status: "ACTIVE",
};
describe("isolated mock IAM contract", () => {
  it("computes KPIs from service state", async () => {
    const d = (await service.handle("GET", "dashboard")) as Dashboard;
    expect(d.totalUsers).toBe(24);
    expect(d.statuses.reduce((sum, s) => sum + s.count, 0)).toBe(d.totalUsers);
    await service.handle("POST", "users", mockSession, {}, user);
    expect(
      ((await service.handle("GET", "dashboard")) as Dashboard).totalUsers,
    ).toBe(25);
  });
  it("filters, sorts and paginates users on the service", async () => {
    const page = (await service.handle("GET", "users", mockSession, {
      status: "ACTIVE",
      page: 2,
      pageSize: 5,
      sort: "name",
    })) as Page<User>;
    expect(page.items).toHaveLength(5);
    expect(page.total).toBe(19);
    expect(page.items.every((u) => u.status === "ACTIVE")).toBe(true);
    const searched = (await service.handle("GET", "users", mockSession, {
      search: "Fatima Khan",
    })) as Page<User>;
    expect(searched.total).toBe(1);
  });
  it("creates ordinary users and rejects duplicates", async () => {
    const result = (await service.handle(
      "POST",
      "users",
      mockSession,
      {},
      user,
    )) as MutationResult;
    expect(result.user?.roleIds).toEqual(["ROLE-1"]);
    expect(
      service.db.scopes.find((s) => s.userId === result.user?.id)?.type,
    ).toBe("OWN");
    await expect(
      service.handle("POST", "users", mockSession, {}, user),
    ).rejects.toMatchObject({ status: 409 });
  });
  it("validates writes before changing state", async () => {
    await expect(
      service.handle(
        "POST",
        "users",
        mockSession,
        {},
        { ...user, email: "invalid" },
      ),
    ).rejects.toThrow();
    expect(service.db.users).toHaveLength(24);
  });
  it("keeps privileged provisioning pending without approved access", async () => {
    const r = (await service.handle(
      "POST",
      "users",
      mockSession,
      {},
      { ...user, roleId: "ROLE-6" },
    )) as MutationResult;
    expect(r.user?.roleIds).toEqual([]);
    expect(r.request?.status).toBe("PENDING");
    expect(service.db.scopes.some((s) => s.userId === r.user?.id)).toBe(false);
  });
  it("blocks self approval in service, then independently applies exactly once", async () => {
    const request = service.createRequest(
      mockSession,
      { kind: "ASSIGN_ROLE", userId: "USER-008", roleId: "ROLE-6" },
      "Approved operational responsibilities",
    );
    await expect(
      service.handle(
        "POST",
        `access-requests/${request.id}/approve`,
        mockSession,
        {},
        { comment: "Reviewed and approved" },
      ),
    ).rejects.toMatchObject({ status: 403 });
    expect(service.db.users[7].roleIds).not.toContain("ROLE-6");
    await service.handle(
      "POST",
      `access-requests/${request.id}/approve`,
      reviewer,
      {},
      { comment: "Reviewed and approved" },
    );
    expect(service.db.users[7].roleIds).toContain("ROLE-6");
    expect(request.status).toBe("APPLIED");
    await expect(
      service.handle(
        "POST",
        `access-requests/${request.id}/approve`,
        reviewer,
        {},
        { comment: "Reviewed again" },
      ),
    ).rejects.toMatchObject({ status: 409 });
  });
  it("rejection never changes approved access", async () => {
    const request = service.createRequest(
      mockSession,
      { kind: "ASSIGN_ROLE", userId: "USER-008", roleId: "ROLE-6" },
      "Approved operational responsibilities",
    );
    await service.handle(
      "POST",
      `access-requests/${request.id}/reject`,
      reviewer,
      {},
      { comment: "Not justified" },
    );
    expect(request.status).toBe("REJECTED");
    expect(service.db.users[7].roleIds).not.toContain("ROLE-6");
  });
  it("permission changes remain pending until independently approved", async () => {
    const r = (await service.handle(
      "POST",
      "access-requests",
      mockSession,
      {},
      {
        change: {
          kind: "GRANT_ROLE_PERMISSION",
          roleId: "ROLE-1",
          permission: "report.read",
        },
        justification: "Reporting for assigned collections",
      },
    )) as { request: AccessRequest };
    expect(service.db.roles[0].permissions).not.toContain("report.read");
    await service.handle(
      "POST",
      `access-requests/${r.request.id}/approve`,
      reviewer,
      {},
      { comment: "Valid use case" },
    );
    expect(service.db.roles[0].permissions).toContain("report.read");
  });
  it("denies unauthorized writes and cross-region management", async () => {
    await expect(
      service.handle(
        "POST",
        "users",
        { ...mockSession, permissions: [] },
        {},
        user,
      ),
    ).rejects.toMatchObject({ status: 403 });
    await expect(
      service.handle("GET", "users/USER-002", {
        ...mockSession,
        regions: ["Sindh"],
      }),
    ).rejects.toMatchObject({ status: 403 });
    await expect(
      service.handle(
        "POST",
        "access-requests",
        mockSession,
        {},
        {
          change: {
            kind: "GRANT_SCOPE",
            userId: "USER-003",
            roleId: "ROLE-2",
            scopeType: "GLOBAL",
            reference: "GLOBAL",
          },
          justification: "Request expanded access",
        },
      ),
    ).rejects.toMatchObject({ status: 403 });
  });
  it("denies customer permissions for system administrator", async () => {
    await expect(
      service.handle(
        "POST",
        "access-requests",
        mockSession,
        {},
        {
          change: {
            kind: "GRANT_ROLE_PERMISSION",
            roleId: "ROLE-6",
            permission: "case.read_portfolio",
          },
          justification: "Request case visibility",
        },
      ),
    ).rejects.toMatchObject({ status: 403 });
  });
  it("enforces separation of policy maker and checker", async () => {
    await expect(
      service.handle(
        "POST",
        "access-requests",
        mockSession,
        {},
        {
          change: { kind: "ASSIGN_ROLE", userId: "USER-005", roleId: "ROLE-5" },
          justification: "Need policy approval access",
        },
      ),
    ).rejects.toMatchObject({ status: 409 });
  });
  it("adds and removes team membership with audit evidence", async () => {
    await service.handle(
      "POST",
      "teams/TEAM-001/members",
      mockSession,
      {},
      { userId: "USER-006", remove: false },
    );
    expect(service.db.teams[0].memberIds).toContain("USER-006");
    expect(service.db.teams[2].memberIds).not.toContain("USER-006");
    await service.handle(
      "POST",
      "teams/TEAM-001/members",
      mockSession,
      {},
      { userId: "USER-006", remove: true },
    );
    expect(service.db.teams[0].memberIds).not.toContain("USER-006");
    expect(service.db.audit[0].action).toBe("Team membership changed");
  });
  it("filters audit events by result and Karachi date boundaries", async () => {
    const events = (await service.handle("GET", "audit-logs", mockSession, {
      result: "DENIED",
      from: "2026-11-06",
      to: "2026-11-06",
    })) as Page<{ result: string; timestamp: string }>;
    expect(events.items.every((e) => e.result === "DENIED")).toBe(true);
    expect(events.total).toBeGreaterThan(0);
  });
  it("mock mode cannot be enabled in production", () => {
    expect(mockEnabled({ NODE_ENV: "production", IAM_ADAPTER: "mock" })).toBe(
      false,
    );
    expect(mockEnabled({ NODE_ENV: "development", IAM_ADAPTER: "mock" })).toBe(
      true,
    );
    expect(mockEnabled({ NODE_ENV: "development" })).toBe(false);
  });
});
it("cannot submit a scope expansion through the ordinary role endpoint", async () => {
  await expect(
    service.handle(
      "POST",
      "users/USER-003/roles",
      mockSession,
      {},
      {
        change: {
          kind: "GRANT_SCOPE",
          userId: "USER-003",
          roleId: "ROLE-2",
          scopeType: "REGION",
          reference: "Punjab",
        },
        justification: "Expanded operational access",
      },
    ),
  ).rejects.toMatchObject({ status: 400 });
});
it("resource permissions require a matching approved role scope", async () => {
  service.db.scopes = service.db.scopes.filter((s) => s.userId !== "USER-008");
  const details = (await service.handle("GET", "users/USER-008")) as {
    permissions: string[];
  };
  expect(details.permissions).not.toContain("case.read_assigned");
});
it("privileged reactivation stays pending and cannot bypass review", async () => {
  service.db.users[4].status = "INACTIVE";
  const result = (await service.handle(
    "POST",
    "users/USER-005/reactivate",
    mockSession,
    {},
    {},
  )) as MutationResult;
  expect(service.db.users[4].status).toBe("INACTIVE");
  expect(result.request?.change.kind).toBe("REACTIVATE_USER");
});
it("new mock sessions reflect approved permission revocations", () => {
  expect(service.session()?.permissions).toContain("iam.user.create");
  service.db.roles[5].permissions = service.db.roles[5].permissions.filter(
    (p) => p !== "iam.user.create",
  );
  expect(service.session()?.permissions).not.toContain("iam.user.create");
});
it("dashboard does not disclose audit records without audit permission", async () => {
  const actor = { ...mockSession, permissions: ["iam.user.read"] };
  const dashboard = (await service.handle(
    "GET",
    "dashboard",
    actor,
  )) as Dashboard;
  expect(dashboard.activity).toEqual([]);
  expect(dashboard.requests).toEqual([]);
});
