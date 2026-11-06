import { seed, type Store, mockSession } from "./fixtures";
import type {
  Session,
  ListParams,
  Page,
  Change,
  AccessRequest,
  User,
  MutationResult,
} from "@/lib/api/types";
import { ApiError } from "@/lib/api/error";
import {
  userSchema,
  teamSchema,
  requestSchema,
  decisionSchema,
} from "@/lib/validation/schemas";
import { can } from "@/lib/auth/policy";
export class MockIamService {
  constructor(public db: Store = seed()) {}
  require(actor: Session, permission: string) {
    if (!can(actor, permission))
      throw new ApiError(403, `Permission required: ${permission}`);
  }
  user(actor: Session, id: string) {
    const user = this.db.users.find((u) => u.id === id);
    if (!user) throw new ApiError(404, "User not found");
    if (!actor.regions.includes(user.region))
      throw new ApiError(403, "User is outside your administrative region");
    return user;
  }
  role(id: string) {
    const r = this.db.roles.find((r) => r.id === id);
    if (!r) throw new ApiError(404, "Role not found");
    return r;
  }
  team(actor: Session, id: string) {
    const t = this.db.teams.find((t) => t.id === id);
    if (!t) throw new ApiError(404, "Team not found");
    if (!actor.regions.includes(t.region))
      throw new ApiError(403, "Team is outside your administrative region");
    return t;
  }
  log(
    actor: Session,
    action: string,
    target: string,
    description: string,
    result: "SUCCESS" | "DENIED" | "FAILURE" = "SUCCESS",
  ) {
    this.db.audit.unshift({
      id: `EVT-${crypto.randomUUID().slice(0, 8)}`,
      timestamp: new Date().toISOString(),
      actor: actor.name,
      action,
      target,
      result,
      source: "IAM administration",
      description,
    });
  }
  page<T extends object>(items: T[], p: ListParams): Page<T> {
    let rows = items.filter((row) => {
      const r = row as Record<string, unknown>;
      if (
        p.search &&
        !JSON.stringify(row).toLowerCase().includes(p.search.toLowerCase())
      )
        return false;
      for (const key of [
        "status",
        "module",
        "actor",
        "action",
        "result",
      ] as const)
        if (p[key] && r[key] !== p[key]) return false;
      if (p.role && !(r.roleIds as string[] | undefined)?.includes(p.role))
        return false;
      if (p.team && r.teamId !== p.team) return false;
      if (
        p.from &&
        new Date(String(r.timestamp)) < new Date(`${p.from}T00:00:00+05:00`)
      )
        return false;
      if (
        p.to &&
        new Date(String(r.timestamp)) > new Date(`${p.to}T23:59:59+05:00`)
      )
        return false;
      return true;
    });
    if (p.sort) {
      const key = p.sort;
      rows = rows.toSorted(
        (a, b) =>
          String((a as Record<string, unknown>)[key] ?? "").localeCompare(
            String((b as Record<string, unknown>)[key] ?? ""),
          ) * (p.direction === "desc" ? -1 : 1),
      );
    }
    const page = Math.max(1, Number(p.page) || 1),
      pageSize = Math.min(100, Math.max(1, Number(p.pageSize) || 8));
    return {
      items: rows.slice((page - 1) * pageSize, page * pageSize),
      total: rows.length,
      page,
      pageSize,
    };
  }
  validateChange(actor: Session, c: Change) {
    const permission =
      c.kind === "GRANT_SCOPE"
        ? "iam.user_role.assign"
        : c.kind === "ASSIGN_ROLE"
          ? "iam.user_role.assign"
          : c.kind === "REVOKE_ROLE"
            ? "iam.user_role.revoke"
            : c.kind === "DEACTIVATE_USER"
              ? "iam.user.deactivate"
              : "iam.permission.assign";
    this.require(actor, permission);
    if ("userId" in c) this.user(actor, c.userId);
    if ("roleId" in c) {
      const role = this.role(c.roleId);
      if (role.phase === "FUTURE" || role.status !== "ACTIVE")
        throw new ApiError(
          409,
          "Future or inactive roles cannot receive access changes",
        );
    }
    if (c.kind === "ASSIGN_ROLE") {
      const user = this.user(actor, c.userId);
      if (user.roleIds.includes(c.roleId))
        throw new ApiError(409, "User already has this role");
      if (
        (c.roleId === "ROLE-4" && user.roleIds.includes("ROLE-5")) ||
        (c.roleId === "ROLE-5" && user.roleIds.includes("ROLE-4"))
      )
        throw new ApiError(409, "Policy maker and approver roles conflict");
    }
    if (
      c.kind === "REVOKE_ROLE" &&
      !this.user(actor, c.userId).roleIds.includes(c.roleId)
    )
      throw new ApiError(409, "Role is no longer assigned");
    if (c.kind === "GRANT_SCOPE") {
      const user = this.user(actor, c.userId);
      if (!user.roleIds.includes(c.roleId))
        throw new ApiError(409, "Scope requires an approved role assignment");
      const allowed =
        c.scopeType === "OWN"
          ? c.reference === user.id
          : c.scopeType === "TEAM"
            ? this.db.teams.some(
                (t) => t.id === c.reference && actor.regions.includes(t.region),
              )
            : c.scopeType === "BRANCH"
              ? this.db.teams.some(
                  (t) =>
                    t.branch === c.reference &&
                    actor.regions.includes(t.region),
                )
              : c.scopeType === "REGION"
                ? actor.regions.includes(c.reference)
                : c.scopeType === "PORTFOLIO"
                  ? c.reference === "PUNJAB-RETAIL" &&
                    actor.regions.includes("Punjab")
                  : false;
      if (!allowed)
        throw new ApiError(
          403,
          "Requested scope exceeds your delegated organizational boundary",
        );
    }
    if (
      c.kind === "GRANT_ROLE_PERMISSION" ||
      c.kind === "REVOKE_ROLE_PERMISSION"
    ) {
      if (!this.db.permissions.some((p) => p.code === c.permission))
        throw new ApiError(400, "Permission is not in the authorized catalog");
      if (c.roleId === "ROLE-6" && !c.permission.startsWith("iam."))
        throw new ApiError(
          403,
          "System Administrator cannot receive customer or collection permissions",
        );
      const has = this.role(c.roleId).permissions.includes(c.permission);
      if (has === (c.kind === "GRANT_ROLE_PERMISSION"))
        throw new ApiError(409, "Permission mapping has already changed");
    }
    if (c.kind === "DEACTIVATE_USER" && c.userId === actor.id)
      throw new ApiError(403, "You cannot deactivate your own account");
  }
  apply(actor: Session, c: Change) {
    this.validateChange(actor, c);
    if (c.kind === "ASSIGN_ROLE")
      this.user(actor, c.userId).roleIds.push(c.roleId);
    if (c.kind === "REVOKE_ROLE") {
      const user = this.user(actor, c.userId);
      user.roleIds = user.roleIds.filter((r) => r !== c.roleId);
      this.db.scopes = this.db.scopes.filter(
        (s) => s.userId !== c.userId || s.roleId !== c.roleId,
      );
    }
    if (c.kind === "GRANT_SCOPE")
      this.db.scopes.push({
        id: `SCOPE-${crypto.randomUUID()}`,
        userId: c.userId,
        roleId: c.roleId,
        type: c.scopeType,
        reference: c.reference,
        region: this.user(actor, c.userId).region,
      });
    if (c.kind === "DEACTIVATE_USER")
      this.user(actor, c.userId).status = "INACTIVE";
    if (c.kind === "GRANT_ROLE_PERMISSION")
      this.role(c.roleId).permissions.push(c.permission);
    if (c.kind === "REVOKE_ROLE_PERMISSION")
      this.role(c.roleId).permissions = this.role(c.roleId).permissions.filter(
        (p) => p !== c.permission,
      );
    this.log(
      actor,
      c.kind.replaceAll("_", " "),
      "userId" in c ? c.userId : c.roleId,
      `${actor.name} applied ${c.kind.toLowerCase().replaceAll("_", " ")}.`,
    );
  }
  createRequest(
    actor: Session,
    c: Change,
    justification: string,
  ): AccessRequest {
    this.require(actor, "iam.access.request");
    this.validateChange(actor, c);
    if (
      this.db.requests.some(
        (r) =>
          r.status === "PENDING" &&
          JSON.stringify(r.change) === JSON.stringify(c),
      )
    )
      throw new ApiError(409, "An identical change is already pending review");
    const user = "userId" in c ? this.user(actor, c.userId) : undefined;
    const target = user?.name ?? this.role("roleId" in c ? c.roleId : "").name;
    const request: AccessRequest = {
      id: `AR-${crypto.randomUUID().slice(0, 6).toUpperCase()}`,
      change: c,
      target,
      requestedBy: actor.id,
      requesterName: actor.name,
      submittedAt: new Date().toISOString(),
      status: "PENDING",
      risk: "High",
      justification,
      existingAccess: user
        ? user.roleIds.map((id) => this.role(id).name)
        : this.role("roleId" in c ? c.roleId : "").permissions,
      proposedAccess:
        c.kind === "GRANT_SCOPE"
          ? `${c.scopeType} · ${c.reference}`
          : c.kind === "ASSIGN_ROLE" || c.kind === "REVOKE_ROLE"
            ? `${c.kind === "REVOKE_ROLE" ? "Revoke " : ""}${this.role(c.roleId).name}`
            : c.kind === "DEACTIVATE_USER"
              ? "Deactivate privileged account"
              : `${c.kind} · ${c.permission}`,
      history: [
        {
          actor: actor.name,
          decision: "Submitted",
          comment: justification,
          at: new Date().toISOString(),
        },
      ],
    };
    this.db.requests.unshift(request);
    this.log(
      actor,
      "Access requested",
      request.id,
      `${actor.name} requested ${request.proposedAccess} for ${target}.`,
    );
    return request;
  }
  async handle(
    method: string,
    path: string,
    actor: Session = mockSession,
    params: ListParams = {},
    body: unknown = {},
  ): Promise<unknown> {
    const [resource, id, action] = path.split("/");
    const db = this.db;
    if (method === "GET") {
      if (resource === "me")
        return action === "permissions" || id === "permissions"
          ? actor.permissions
          : actor;
      const perm: Record<string, string> = {
        dashboard: "iam.user.read",
        users: "iam.user.read",
        roles: "iam.role.read",
        permissions: "iam.permission.read",
        teams: "iam.team.read",
        scopes: "iam.user.read",
        "access-requests": "iam.access.request",
        "audit-logs": "iam.audit.read",
        settings: "iam.role.read",
      };
      if (!perm[resource]) throw new ApiError(404, "Endpoint not found");
      this.require(actor, perm[resource]);
      const users = db.users.filter((u) => actor.regions.includes(u.region));
      if (resource === "dashboard")
        return {
          totalUsers: users.length,
          activeUsers: users.filter((u) => u.status === "ACTIVE").length,
          inactiveUsers: users.filter((u) =>
            ["INACTIVE", "SUSPENDED"].includes(u.status),
          ).length,
          totalRoles: db.roles.length,
          pendingRequests: db.requests.filter((r) => r.status === "PENDING")
            .length,
          activeTeams: db.teams.filter(
            (t) => t.status === "ACTIVE" && actor.regions.includes(t.region),
          ).length,
          statuses: [
            "ACTIVE",
            "INACTIVE",
            "SUSPENDED",
            "PENDING_ACTIVATION",
          ].map((status) => ({
            status,
            count: users.filter((u) => u.status === status).length,
          })),
          requests: db.requests
            .filter((r) => r.status === "PENDING")
            .slice(0, 4),
          activity: db.audit.slice(0, 5),
        };
      if (resource === "users") {
        if (!id) return this.page(users, params);
        const user = this.user(actor, id);
        if (action === "roles") return user.roleIds.map((id) => this.role(id));
        if (action === "scopes")
          return db.scopes.filter((s) => s.userId === id);
        const roles = user.roleIds.map((id) => this.role(id));
        return {
          user,
          roles,
          permissions: [...new Set(roles.flatMap((r) => r.permissions))],
          scopes: db.scopes.filter((s) => s.userId === id),
          teams: db.teams.filter((t) => t.memberIds.includes(id)),
          audit: db.audit.filter((e) => e.target === id),
        };
      }
      if (resource === "roles") {
        const roles = db.roles.map((r) => ({
          ...r,
          userCount: users.filter((u) => u.roleIds.includes(r.id)).length,
        }));
        if (!id) return this.page(roles, params);
        const role = roles.find((r) => r.id === id);
        if (!role) throw new ApiError(404, "Role not found");
        if (action === "permissions")
          return db.permissions.filter((p) =>
            role.permissions.includes(p.code),
          );
        return {
          role,
          users: users.filter((u) => u.roleIds.includes(id)),
          permissions: db.permissions,
          audit: db.audit.filter((e) => e.target === id),
        };
      }
      if (resource === "permissions")
        return this.page(
          db.permissions.map((p) => ({
            ...p,
            roleIds: db.roles
              .filter((r) => r.permissions.includes(p.code))
              .map((r) => r.id),
          })),
          params,
        );
      if (resource === "teams")
        return this.page(
          db.teams.filter((t) => actor.regions.includes(t.region)),
          params,
        );
      if (resource === "scopes")
        return this.page(
          db.scopes.filter((s) => users.some((u) => u.id === s.userId)),
          params,
        );
      if (resource === "access-requests") {
        if (id) {
          const request = db.requests.find((r) => r.id === id);
          if (!request) throw new ApiError(404, "Request not found");
          return request;
        }
        return this.page(db.requests, params);
      }
      if (resource === "audit-logs") return this.page(db.audit, params);
      if (resource === "settings")
        return {
          identityProvider:
            "Development identity adapter · live OIDC not connected",
          sessionPolicy:
            "Live session policy unavailable until IAM integration",
          approvalPolicy:
            "Independent maker-checker enforced for privileged access, role permissions and expanded scope",
          reviewPeriod: "Quarterly access review · scheduling planned",
          catalog: "10 system-defined roles · seed-managed permission catalog",
        };
    }
    if (resource === "users" && method === "POST" && !id) {
      this.require(actor, "iam.user.create");
      const data = userSchema.parse(body);
      const team = this.team(actor, data.teamId);
      const role = this.role(data.roleId);
      if (role.status !== "ACTIVE")
        throw new ApiError(400, "Role is not available");
      if (
        db.users.some(
          (u) =>
            u.username === data.username ||
            u.email === data.email ||
            u.employeeReference === data.employeeReference,
        )
      )
        throw new ApiError(
          409,
          "Username, email or employee reference already exists",
        );
      const user: User = {
        id: `USER-${crypto.randomUUID().slice(0, 8)}`,
        name: data.name,
        username: data.username,
        email: data.email,
        employeeReference: data.employeeReference,
        roleIds: role.privileged ? [] : [role.id],
        teamId: team.id,
        region: team.region,
        status: data.status,
        createdAt: new Date().toISOString(),
      };
      this.require(actor, "iam.user_role.assign");
      this.require(actor, "iam.team.manage");
      if (role.privileged) this.require(actor, "iam.access.request");
      db.users.push(user);
      team.memberIds.push(user.id);
      let request: AccessRequest | undefined;
      if (role.privileged)
        request = this.createRequest(
          actor,
          { kind: "ASSIGN_ROLE", userId: user.id, roleId: role.id },
          "Initial privileged role assignment requested during user provisioning.",
        );
      else
        db.scopes.push({
          id: `SCOPE-${crypto.randomUUID()}`,
          userId: user.id,
          roleId: role.id,
          type: data.scopeType,
          reference:
            data.scopeType === "OWN"
              ? user.id
              : data.scopeType === "TEAM"
                ? team.id
                : team.branch,
          region: team.region,
        });
      this.log(
        actor,
        "User created",
        user.id,
        `${actor.name} created ${user.name}.`,
      );
      return {
        user,
        request,
        message: request
          ? "User created. Privileged role is pending independent approval."
          : "User created with approved ordinary access.",
      } satisfies MutationResult;
    }
    if (resource === "users" && id && method === "PATCH") {
      this.require(actor, "iam.user.update");
      const user = this.user(actor, id);
      const data = userSchema
        .pick({ name: true, email: true, employeeReference: true })
        .parse(body);
      if (
        db.users.some(
          (u) =>
            u.id !== id &&
            (u.email === data.email ||
              u.employeeReference === data.employeeReference),
        )
      )
        throw new ApiError(409, "Email or employee reference already exists");
      Object.assign(user, data);
      this.log(
        actor,
        "User updated",
        id,
        `${actor.name} updated ${user.name}'s profile.`,
      );
      return { message: "Profile updated" };
    }
    if (
      resource === "users" &&
      id &&
      method === "POST" &&
      (action === "deactivate" || action === "reactivate")
    ) {
      this.require(actor, "iam.user.deactivate");
      const user = this.user(actor, id);
      if (user.id === actor.id)
        throw new ApiError(403, "You cannot change your own account status");
      if (
        user.roleIds.some((id) => this.role(id).privileged) &&
        action === "deactivate"
      )
        return {
          message: "Deactivation submitted for approval",
          request: this.createRequest(
            actor,
            { kind: "DEACTIVATE_USER", userId: id },
            "Privileged account deactivation requested by administrator.",
          ),
        };
      user.status = action === "deactivate" ? "INACTIVE" : "ACTIVE";
      this.log(
        actor,
        action === "deactivate" ? "User deactivated" : "User reactivated",
        id,
        `${actor.name} ${action}d ${user.name}.`,
      );
      return { message: "Account status updated" };
    }
    if (resource === "users" && action === "roles" && method === "POST") {
      const c = requestSchema.parse(body);
      if (!("userId" in c.change) || c.change.userId !== id)
        throw new ApiError(400, "Target mismatch");
      this.validateChange(actor, c.change);
      const privileged =
        "roleId" in c.change && this.role(c.change.roleId).privileged;
      if (privileged)
        return {
          message: "Role change is pending approval",
          request: this.createRequest(actor, c.change, c.justification),
        };
      this.apply(actor, c.change);
      return { message: "Role assignment updated" };
    }
    if (resource === "teams" && (method === "POST" || method === "PATCH")) {
      this.require(actor, "iam.team.manage");
      if (id && action === "members") {
        const data = (await import("zod")).z
          .object({
            userId: (await import("zod")).z.string(),
            remove: (await import("zod")).z.boolean(),
          })
          .parse(body);
        const team = this.team(actor, id),
          user = this.user(actor, data.userId);
        if (data.remove && team.supervisorId === user.id)
          throw new ApiError(
            409,
            "Assign a replacement supervisor before removal",
          );
        if (data.remove) {
          team.memberIds = team.memberIds.filter((u) => u !== user.id);
          if (user.teamId === team.id) user.teamId = "";
        } else {
          if (user.teamId && user.teamId !== team.id) {
            const old = this.team(actor, user.teamId);
            if (old.supervisorId === user.id)
              throw new ApiError(
                409,
                "Replace the supervisor in the current team first",
              );
            old.memberIds = old.memberIds.filter((u) => u !== user.id);
          }
          if (!team.memberIds.includes(user.id)) team.memberIds.push(user.id);
          user.teamId = team.id;
        }
        this.log(
          actor,
          "Team membership changed",
          user.id,
          `${actor.name} ${data.remove ? "removed" : "added"} ${user.name} ${data.remove ? "from" : "to"} ${team.name}.`,
        );
        return { message: "Team membership updated" };
      }
      const data = teamSchema.parse(body);
      if (!actor.regions.includes(data.region))
        throw new ApiError(403, "Region outside delegated boundary");
      const supervisor = this.user(actor, data.supervisorId);
      if (
        !supervisor.roleIds.includes("ROLE-2") ||
        supervisor.status !== "ACTIVE"
      )
        throw new ApiError(400, "Select an active Collection Supervisor");
      if (db.teams.some((t) => t.code === data.code && t.id !== id))
        throw new ApiError(409, "Team code already exists");
      if (id) {const team=this.team(actor,id);Object.assign(team,data);if(!team.memberIds.includes(data.supervisorId))team.memberIds.push(data.supervisorId);}
      else
        db.teams.push({
          ...data,
          id: `TEAM-${crypto.randomUUID().slice(0, 6)}`,
          memberIds: [data.supervisorId],
          createdAt: new Date().toISOString(),
        });
      this.log(
        actor,
        "Team updated",
        id ?? data.code,
        `${actor.name} saved ${data.name}.`,
      );
      return { message: "Team saved" };
    }
    if (resource === "scopes" && id && method === "DELETE") {
      this.require(actor, "iam.user_role.revoke");
      const scope = db.scopes.find((s) => s.id === id);
      if (!scope) throw new ApiError(404, "Scope not found");
      this.user(actor, scope.userId);
      db.scopes = db.scopes.filter((s) => s.id !== id);
      this.log(
        actor,
        "Scope revoked",
        scope.userId,
        `${actor.name} revoked ${scope.type} scope ${scope.reference}.`,
      );
      return { message: "Scope revoked" };
    }
    if (resource === "access-requests" && method === "POST") {
      if (!id) {
        const data = requestSchema.parse(body);
        return {
          request: this.createRequest(actor, data.change, data.justification),
          message: "Access request submitted for independent review",
        };
      }
      this.require(actor, "iam.access.approve");
      const data = decisionSchema.parse(body);
      const request = db.requests.find((r) => r.id === id);
      if (!request) throw new ApiError(404, "Request not found");
      if (!["approve", "reject"].includes(action))
        throw new ApiError(404, "Unknown decision");
      if (request.requestedBy === actor.id) {
        this.log(
          actor,
          "Self-approval blocked",
          id,
          "Requester cannot review their own request.",
          "DENIED",
        );
        throw new ApiError(
          403,
          "An independent approver must review your request",
        );
      }
      if (request.status !== "PENDING")
        throw new ApiError(409, "Request has already been reviewed");
      this.validateChange(actor, request.change);
      if (action === "approve") this.apply(actor, request.change);
      request.status = action === "approve" ? "APPLIED" : "REJECTED";
      request.history.push({
        actor: actor.name,
        decision: action === "approve" ? "Approved and applied" : "Rejected",
        comment: data.comment,
        at: new Date().toISOString(),
      });
      this.log(
        actor,
        action === "approve" ? "Access approved" : "Access rejected",
        id,
        `${actor.name} ${action}d ${request.proposedAccess} for ${request.target}.`,
      );
      return {
        message:
          action === "approve"
            ? "Approved access applied and audited"
            : "Request rejected and audited",
      };
    }
    throw new ApiError(404, "Endpoint not available");
  }
}
declare global {
  var __mockIam: MockIamService | undefined;
}
export function mockService() {
  return (globalThis.__mockIam ??= new MockIamService());
}
