import "server-only";
import { ApiError } from "@/lib/api/error";
import { can } from "@/lib/auth/policy";
import type {
  AccessRequest,
  AuditEvent,
  Change,
  Dashboard,
  ListParams,
  MutationResult,
  Page,
  Permission,
  Role,
  Scope,
  ScopeType,
  Session,
  Team,
  User,
} from "@/lib/api/types";

/**
 * Live adapter: translates the identity-access-service REST API (snake_case, UUIDs,
 * limit/offset pages, Bearer access tokens) into the view models the admin UI consumes.
 * Authorization is always decided by IAM; this layer only maps shapes.
 */

type Json = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any


export function iamBaseUrl() {
  const base = process.env.IAM_API_BASE_URL;
  if (!base) throw new ApiError(503, "IAM_API_BASE_URL is not configured");
  return base.replace(/\/$/, "");
}

async function call<T = Json>(
  token: string,
  method: string,
  path: string,
  opts: { query?: Record<string, unknown>; body?: unknown } = {},
): Promise<T> {
  const query = new URLSearchParams();
  Object.entries(opts.query ?? {}).forEach(([k, v]) => {
    if (v !== undefined && v !== "" && v !== null) query.set(k, String(v));
  });
  const response = await fetch(
    `${iamBaseUrl()}/api/v1/${path}${query.size ? `?${query}` : ""}`,
    {
      method,
      headers: {
        Authorization: `Bearer ${token}`,
        ...(opts.body === undefined
          ? {}
          : { "Content-Type": "application/json" }),
      },
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
      signal: AbortSignal.timeout(15000),
      cache: "no-store",
      redirect: "error",
    },
  );
  if (response.status === 204) return undefined as T;
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data?.error?.message ?? data?.detail;
    throw new ApiError(
      response.status,
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((d: Json) => d.msg).join("; ")
          : "IAM could not complete the request",
    );
  }
  return data as T;
}

/** Walks every page of a limit/offset collection (the service caps limit at 200). */
async function all(
  token: string,
  path: string,
  query: Record<string, unknown> = {},
): Promise<Json[]> {
  const rows: Json[] = [];
  for (let offset = 0; offset < 5000; offset += 200) {
    const page = await call<{ items: Json[]; total: number }>(
      token,
      "GET",
      path,
      { query: { ...query, limit: 200, offset } },
    );
    rows.push(...page.items);
    if (rows.length >= page.total || page.items.length === 0) break;
  }
  return rows;
}

/* ---------- session ---------- */

export async function liveSession(token: string): Promise<Session> {
  const me = await call(token, "GET", "me");
  const perms = await call(token, "GET", "me/permissions");
  let email = "";
  try {
    email = (await call(token, "GET", `users/${me.user_id}`)).email;
  } catch {
    /* caller may lack iam.user.read; the UI only displays the address */
  }
  const scopes: Json[] = me.scopes ?? [];
  const regions = scopes.some((s) => s.scope_type === "GLOBAL")
    ? ["All regions"]
    : scopes.map((s) => s.scope_value ?? s.scope_type);
  return {
    id: me.user_id,
    name: me.display_name,
    email,
    role: (me.roles ?? [])[0] ?? "",
    permissions: (perms.permissions ?? []).map((p: Json) => p.code),
    regions: regions.length ? regions : ["Own records"],
    mock: false,
  };
}

/* ---------- mappers ---------- */

const mapUser = (u: Json, roleIds: string[] = [], teamId = ""): User => ({
  id: u.id,
  name: u.display_name,
  username: u.username,
  email: u.email,
  employeeReference: u.external_identity_id,
  roleIds,
  teamId,
  region: "",
  status: u.status,
  createdAt: u.created_at,
});

const mapRole = (
  r: Json,
  permissions: string[] = [],
  userCount = 0,
): Role => ({
  id: r.id,
  name: r.name,
  code: r.code,
  description: r.description ?? "",
  permissions,
  privileged: r.is_privileged,
  system: r.is_system,
  phase: String(r.phase).toUpperCase() === "FUTURE" ? "FUTURE" : "MVP",
  status: r.status,
  userCount,
});

const mapTeam = (t: Json, members: Json[] = []): Team => ({
  id: t.id,
  name: t.name,
  code: t.code,
  supervisorId: members.find((m) => m.member_role === "LEAD")?.user_id ?? "",
  memberIds: members.map((m) => m.user_id),
  branch: t.branch_id ?? "",
  region: t.region_id ?? "",
  status: t.status,
  createdAt: t.created_at,
});

const mapPermission = (p: Json, roleIds: string[] = []): Permission => ({
  id: p.id,
  code: p.code,
  description: p.description,
  module: p.category,
  action: String(p.code).split(".").pop() ?? "",
  sensitive: p.is_sensitive,
  allowedScopes: p.allowed_scope_types,
  roleIds,
});

const mapUserScope = (g: Json, region = ""): Scope => ({
  id: `${g.user_id}~${g.id}`,
  userId: g.user_id,
  roleId: "",
  type: g.scope.scope_type as ScopeType,
  reference: g.scope.scope_value ?? g.scope.name,
  region,
});

const mapAudit = (e: Json, names: Map<string, string>): AuditEvent => ({
  id: String(e.id),
  timestamp: e.occurred_at,
  actor:
    (e.actor_user_id && names.get(e.actor_user_id)) ||
    e.actor_ref ||
    (e.actor_type === "SERVICE" ? "Service" : "System"),
  action: e.action,
  target: e.target_id ?? "",
  result: e.outcome,
  source: e.actor_type === "SERVICE" ? "Service API" : "IAM administration",
  description: [
    e.action,
    e.target_type && `on ${e.target_type}`,
    e.target_id,
    e.details?.reason && `(${e.details.reason})`,
  ]
    .filter(Boolean)
    .join(" "),
});

/* ---------- shared lookups ---------- */

interface Directory {
  users: Json[];
  roles: Json[];
  userRoles: Map<string, string[]>;
  rolePermissions: Map<string, string[]>;
  teams: Json[];
  members: Map<string, Json[]>;
  names: Map<string, string>;
}
const cache = new Map<string, { at: number; value: Directory }>();

/** Per-token, 15 s cache of the reference data most pages need (avoids N+1 storms per click). */
async function directory(token: string): Promise<Directory> {
  const hit = cache.get(token);
  if (hit && Date.now() - hit.at < 15000) return hit.value;
  const [users, roles, teams] = await Promise.all([
    all(token, "users").catch(() => []),
    all(token, "roles").catch(() => []),
    all(token, "teams").catch(() => []),
  ]);
  const userRoles = new Map<string, string[]>();
  const rolePermissions = new Map<string, string[]>();
  const members = new Map<string, Json[]>();
  await Promise.all([
    ...users.map(async (u) => {
      const rows = await call<Json[]>(token, "GET", `users/${u.id}/roles`).catch(
        () => [],
      );
      userRoles.set(
        u.id,
        rows.filter((r) => r.status === "ACTIVE").map((r) => r.role.id),
      );
    }),
    ...roles.map(async (r) => {
      const rows = await call<Json[]>(
        token,
        "GET",
        `roles/${r.id}/permissions`,
      ).catch(() => []);
      rolePermissions.set(
        r.id,
        rows.map((p) => p.code),
      );
    }),
    ...teams.map(async (t) => {
      members.set(
        t.id,
        await call<Json[]>(token, "GET", `teams/${t.id}/members`).catch(
          () => [],
        ),
      );
    }),
  ]);
  const value: Directory = {
    users,
    roles,
    userRoles,
    rolePermissions,
    teams,
    members,
    names: new Map(users.map((u) => [u.id, u.display_name])),
  };
  cache.set(token, { at: Date.now(), value });
  if (cache.size > 50) cache.delete(cache.keys().next().value!);
  return value;
}
const invalidate = (token: string) => cache.delete(token);

const userTeam = (d: Directory, userId: string) =>
  d.teams.find((t) =>
    (d.members.get(t.id) ?? []).some((m) => m.user_id === userId),
  )?.id ?? "";
const toUser = (d: Directory, u: Json) =>
  mapUser(u, d.userRoles.get(u.id), userTeam(d, u.id));
const toRole = (d: Directory, r: Json) =>
  mapRole(
    r,
    d.rolePermissions.get(r.id),
    [...d.userRoles.values()].filter((ids) => ids.includes(r.id)).length,
  );
const toTeam = (d: Directory, t: Json) => mapTeam(t, d.members.get(t.id));

function paginate<T extends object>(items: T[], p: ListParams): Page<T> {
  const search = p.search?.toLowerCase();
  let rows = items.filter((row) => {
    const r = row as Record<string, unknown>;
    if (search && !JSON.stringify(row).toLowerCase().includes(search))
      return false;
    for (const key of ["status", "module", "actor", "action", "result"] as const)
      if (p[key] && r[key] !== p[key]) return false;
    if (p.role && !(r.roleIds as string[] | undefined)?.includes(p.role))
      return false;
    if (p.team && r.teamId !== p.team) return false;
    return true;
  });
  if (p.sort) {
    const key = p.sort;
    rows = rows.toSorted((a, b) => {
      const l = (a as Record<string, unknown>)[key];
      const r = (b as Record<string, unknown>)[key];
      const c =
        typeof l === "number" && typeof r === "number"
          ? l - r
          : String(l ?? "").localeCompare(String(r ?? ""));
      return c * (p.direction === "desc" ? -1 : 1);
    });
  }
  const pageSize = Math.min(100, Math.max(1, Math.floor(Number(p.pageSize) || 8)));
  const page = Math.min(
    Math.max(1, Math.ceil(rows.length / pageSize)),
    Math.max(1, Math.floor(Number(p.page) || 1)),
  );
  return {
    items: rows.slice((page - 1) * pageSize, page * pageSize),
    total: rows.length,
    page,
    pageSize,
  };
}

/* ---------- access requests ---------- */

function mapRequest(r: Json, d: Directory): AccessRequest {
  const role = d.roles.find((x) => x.id === r.role_id);
  const userName = d.names.get(r.target_user_id);
  const permCode = r.permission_id; // resolved by caller when catalog is loaded
  let change: Change;
  let proposedAccess: string;
  switch (r.request_type) {
    case "ASSIGN_ROLE":
      change = { kind: "ASSIGN_ROLE", userId: r.target_user_id, roleId: r.role_id };
      proposedAccess = `Role ${role?.name ?? r.role_id}`;
      break;
    case "GRANT_SCOPE":
      change = {
        kind: "GRANT_SCOPE",
        userId: r.target_user_id,
        roleId: "",
        scopeType: "TEAM",
        reference: r.scope_id,
      };
      proposedAccess = `Scope ${r.scope_id}`;
      break;
    default:
      change = {
        kind: r.request_type,
        roleId: r.role_id,
        permission: permCode,
      } as Change;
      proposedAccess = `Permission ${permCode} on ${role?.name ?? r.role_id}`;
  }
  const history = (r.approvals ?? []).map((a: Json) => ({
    actor: d.names.get(a.approver_id) ?? a.approver_id,
    decision: a.decision === "APPROVED" ? "Approved and applied" : "Rejected",
    comment: a.comment ?? "",
    at: a.decided_at,
  }));
  if (r.status === "FAILED")
    history.push({
      actor: "IAM",
      decision: "Approved but could not be applied",
      comment: r.failure_reason ?? "",
      at: r.decided_at ?? r.created_at,
    });
  return {
    id: r.id,
    change,
    target: userName ?? role?.name ?? "",
    requestedBy: r.requested_by,
    requesterName: d.names.get(r.requested_by) ?? r.requested_by,
    submittedAt: r.created_at,
    status: r.status === "FAILED" ? "REJECTED" : r.status,
    risk: role?.is_privileged ? "High" : "Standard",
    justification: r.justification,
    existingAccess: [],
    proposedAccess,
    history,
  };
}

async function toRequests(token: string, rows: Json[], d: Directory) {
  const perms = new Map<string, string>();
  if (rows.some((r) => r.permission_id))
    (await all(token, "permissions").catch(() => [])).forEach((p) =>
      perms.set(p.id, p.code),
    );
  return rows.map((r) =>
    mapRequest({ ...r, permission_id: perms.get(r.permission_id) ?? r.permission_id }, d),
  );
}

async function toRequestBody(
  token: string,
  change: Change,
  justification: string,
): Promise<Json> {
  switch (change.kind) {
    case "ASSIGN_ROLE":
      return {
        request_type: "ASSIGN_ROLE",
        target_user_id: change.userId,
        role_id: change.roleId,
        justification,
      };
    case "GRANT_SCOPE": {
      const scope = (await all(token, "scopes")).find(
        (s) =>
          s.scope_type === change.scopeType &&
          (s.scope_value ?? "") === (change.reference ?? ""),
      );
      if (!scope)
        throw new ApiError(
          404,
          `No ${change.scopeType} scope "${change.reference}" is defined in IAM`,
        );
      return {
        request_type: "GRANT_SCOPE",
        target_user_id: change.userId,
        scope_id: scope.id,
        justification,
      };
    }
    case "GRANT_ROLE_PERMISSION":
    case "REVOKE_ROLE_PERMISSION": {
      const permission = (await all(token, "permissions")).find(
        (p) => p.code === change.permission,
      );
      if (!permission)
        throw new ApiError(404, `Permission ${change.permission} not found`);
      return {
        request_type: change.kind,
        role_id: change.roleId,
        permission_id: permission.id,
        justification,
      };
    }
    default:
      throw new ApiError(
        400,
        "This change type is applied directly in IAM and cannot be submitted as an access request",
      );
  }
}

/* ---------- entry point ---------- */

const slug = (v: string) => v.trim().toUpperCase().replace(/[^A-Z0-9]+/g, "-");

export async function liveHandle(
  method: string,
  path: string,
  actor: Session,
  token: string,
  params: ListParams,
  body: Json,
): Promise<unknown> {
  const [resource, id, action] = path.split("/");
  if (method === "GET") return read(resource, id, action, actor, token, params);
  try {
    return await write(method, resource, id, action, actor, token, body);
  } finally {
    invalidate(token);
  }
}

async function read(
  resource: string,
  id: string | undefined,
  action: string | undefined,
  actor: Session,
  token: string,
  p: ListParams,
): Promise<unknown> {
  if (resource === "me")
    return id === "permissions" ? actor.permissions : actor;
  if (resource === "settings")
    return {
      identityProvider: "Username and password · verified by the IAM service",
      sessionPolicy: "Bearer access token held in an httpOnly cookie; lifetime set by the IAM service",
      approvalPolicy:
        "Independent maker-checker enforced for privileged roles, sensitive permissions and escalating scopes",
      reviewPeriod: "Quarterly access review · scheduling planned",
      catalog: "Seed-managed permission catalog (read-only over the API)",
    };
  if (resource === "audit-logs") {
    const pageSize = Math.min(100, Math.max(1, Number(p.pageSize) || 8));
    const page = Math.max(1, Number(p.page) || 1);
    const [res, d] = await Promise.all([
      call<{ items: Json[]; total: number }>(token, "GET", "audit-logs", {
        query: {
          action: p.action,
          outcome: p.result,
          occurred_from: p.from && `${p.from}T00:00:00+05:00`,
          occurred_to: p.to && `${p.to}T23:59:59+05:00`,
          limit: pageSize,
          offset: (page - 1) * pageSize,
        },
      }),
      directory(token),
    ]);
    return {
      items: res.items.map((e) => mapAudit(e, d.names)),
      total: res.total,
      page,
      pageSize,
    };
  }
  const d = await directory(token);
  switch (resource) {
    case "dashboard": {
      const users = d.users.map((u) => toUser(d, u));
      const [requests, activity] = await Promise.all([
        can(actor, "iam.access.request")
          ? all(token, "access-requests", { status: "PENDING" })
              .then((rows) => toRequests(token, rows.slice(0, 4), d))
              .catch(() => [])
          : [],
        can(actor, "iam.audit.read")
          ? call<{ items: Json[] }>(token, "GET", "audit-logs", {
              query: { limit: 5 },
            })
              .then((r) => r.items.map((e) => mapAudit(e, d.names)))
              .catch(() => [])
          : [],
      ]);
      const count = (s: string) => users.filter((u) => u.status === s).length;
      return {
        totalUsers: users.length,
        activeUsers: count("ACTIVE"),
        inactiveUsers: count("INACTIVE"),
        totalRoles: d.roles.length,
        pendingRequests: requests.length,
        activeTeams: d.teams.filter((t) => t.status === "ACTIVE").length,
        statuses: (
          ["ACTIVE", "INACTIVE", "SUSPENDED", "PENDING_ACTIVATION"] as const
        ).map((status) => ({ status, count: count(status) })),
        requests,
        activity,
      } satisfies Dashboard;
    }
    case "users": {
      if (!id) return paginate(d.users.map((u) => toUser(d, u)), p);
      const u = d.users.find((x) => x.id === id);
      if (!u) throw new ApiError(404, "User not found");
      const user = toUser(d, u);
      const roles = user.roleIds
        .map((rid) => d.roles.find((r) => r.id === rid))
        .filter(Boolean)
        .map((r) => toRole(d, r!));
      const grants = await call<Json[]>(token, "GET", `users/${id}/scopes`).catch(
        () => [],
      );
      if (action === "roles") return roles;
      if (action === "scopes") return grants.map((g) => mapUserScope(g));
      const audit = can(actor, "iam.audit.read")
        ? await call<{ items: Json[] }>(token, "GET", "audit-logs", {
            query: { target_id: id, limit: 10 },
          })
            .then((r) => r.items.map((e) => mapAudit(e, d.names)))
            .catch(() => [])
        : [];
      return {
        user,
        roles,
        permissions:
          user.status !== "ACTIVE"
            ? []
            : [...new Set(roles.flatMap((r) => r.permissions))],
        scopes: grants.map((g) => mapUserScope(g)),
        teams: d.teams
          .filter((t) => (d.members.get(t.id) ?? []).some((m) => m.user_id === id))
          .map((t) => toTeam(d, t)),
        audit,
      };
    }
    case "roles": {
      const roles = d.roles.map((r) => toRole(d, r));
      if (!id) return paginate(roles, p);
      const role = roles.find((r) => r.id === id);
      if (!role) throw new ApiError(404, "Role not found");
      const catalog = await permissionRows(token, d);
      if (action === "permissions")
        return catalog.filter((x) => role.permissions.includes(x.code));
      const audit = can(actor, "iam.audit.read")
        ? await call<{ items: Json[] }>(token, "GET", "audit-logs", {
            query: { target_id: id, limit: 10 },
          })
            .then((r) => r.items.map((e) => mapAudit(e, d.names)))
            .catch(() => [])
        : [];
      return {
        role,
        users: d.users
          .filter((u) => d.userRoles.get(u.id)?.includes(id))
          .map((u) => toUser(d, u)),
        permissions: catalog,
        audit,
      };
    }
    case "permissions":
      return paginate(await permissionRows(token, d), p);
    case "teams":
      if (id) {
        const t = d.teams.find((x) => x.id === id);
        if (!t) throw new ApiError(404, "Team not found");
        return toTeam(d, t);
      }
      return paginate(d.teams.map((t) => toTeam(d, t)), p);
    case "scopes": {
      const grants = (
        await Promise.all(
          d.users.map((u) =>
            call<Json[]>(token, "GET", `users/${u.id}/scopes`).catch(() => []),
          ),
        )
      ).flat();
      return paginate(grants.map((g) => mapUserScope(g)), p);
    }
    case "access-requests": {
      if (id) {
        const row = await call(token, "GET", `access-requests/${id}`);
        return (await toRequests(token, [row], d))[0];
      }
      const rows = await all(token, "access-requests");
      return paginate(await toRequests(token, rows, d), p);
    }
  }
  throw new ApiError(404, "Endpoint not found");
}

async function permissionRows(token: string, d: Directory) {
  const rows = await all(token, "permissions");
  return rows.map((p) =>
    mapPermission(
      p,
      d.roles
        .filter((r) => d.rolePermissions.get(r.id)?.includes(p.code))
        .map((r) => r.id),
    ),
  );
}

async function write(
  method: string,
  resource: string,
  id: string | undefined,
  action: string | undefined,
  actor: Session,
  token: string,
  body: Json,
): Promise<MutationResult> {
  // Users
  if (resource === "users" && method === "POST" && !id) {
    const d = await directory(token);
    const created = await call(token, "POST", "users", {
      body: {
        external_identity_id: body.employeeReference,
        username: body.username,
        display_name: body.name,
        email: body.email,
      },
    });
    const notes: string[] = [];
    const role = d.roles.find((r) => r.id === body.roleId);
    try {
      if (role?.is_privileged)
        notes.push("privileged role left pending maker-checker approval");
      else if (role)
        await call(token, "POST", `users/${created.id}/roles`, {
          body: { role_id: role.id },
        });
      if (body.teamId)
        await call(token, "POST", `teams/${body.teamId}/members`, {
          body: { user_id: created.id },
        });
      const team = d.teams.find((t) => t.id === body.teamId);
      const wanted =
        body.scopeType === "TEAM"
          ? team?.code
          : body.scopeType === "BRANCH"
            ? team?.branch_id
            : null;
      const scopes = await all(token, "scopes");
      const scope = scopes.find(
        (s) => s.scope_type === body.scopeType && (s.scope_value ?? null) === (wanted ?? null),
      );
      if (scope)
        await call(token, "POST", `users/${created.id}/scopes`, {
          body: { scope_id: scope.id },
        });
      else notes.push(`no ${body.scopeType} scope exists to grant`);
      if (body.status === "INACTIVE")
        await call(token, "POST", `users/${created.id}/deactivate`);
    } catch (error) {
      throw new ApiError(
        error instanceof ApiError ? error.status : 502,
        `User created, but follow-up setup failed: ${(error as Error).message}`,
      );
    }
    return {
      message: `User created${notes.length ? ` (${notes.join("; ")})` : ""}`,
      user: mapUser(created, role && !role.is_privileged ? [role.id] : []),
    };
  }
  if (resource === "users" && id && !action && method === "PATCH") {
    const u = await call(token, "PATCH", `users/${id}`, {
      body: { display_name: body.name, email: body.email },
    });
    return { message: "User updated", user: mapUser(u) };
  }
  if (resource === "users" && id && (action === "deactivate" || action === "reactivate")) {
    await call(token, "POST", `users/${id}/${action}`);
    return { message: `User ${action}d` };
  }
  if (resource === "users" && id && action === "roles" && method === "POST") {
    const change = body.change as Change;
    if (change?.kind !== "ASSIGN_ROLE")
      throw new ApiError(400, "Unsupported role change");
    const d = await directory(token);
    const role = d.roles.find((r) => r.id === change.roleId);
    if (!role) throw new ApiError(404, "Role not found");
    if (role.is_privileged || !can(actor, "iam.user_role.assign")) {
      const request = await call(token, "POST", "access-requests", {
        body: await toRequestBody(token, change, body.justification),
      });
      return {
        message: "Access request submitted for independent review",
        request: (await toRequests(token, [request], d))[0],
      };
    }
    await call(token, "POST", `users/${id}/roles`, { body: { role_id: role.id } });
    return { message: "Role assigned and audited" };
  }
  // Teams
  if (resource === "teams" && !action && (method === "POST" || method === "PATCH")) {
    const fields = {
      name: body.name,
      branch_id: body.branch || undefined,
      region_id: body.region ? slug(body.region) : undefined,
      status: body.status,
    };
    const team =
      method === "POST"
        ? await call(token, "POST", "teams", { body: { ...fields, code: body.code } })
        : await call(token, "PATCH", `teams/${id}`, { body: fields });
    if (body.supervisorId)
      await call(token, "POST", `teams/${team.id}/members`, {
        body: { user_id: body.supervisorId, member_role: "LEAD" },
      }).catch((e: ApiError) => {
        if (e.status !== 409) throw e;
      });
    return { message: method === "POST" ? "Team created" : "Team updated" };
  }
  if (resource === "teams" && id && action === "members") {
    if (body.remove)
      await call(token, "DELETE", `teams/${id}/members/${body.userId}`);
    else
      await call(token, "POST", `teams/${id}/members`, {
        body: { user_id: body.userId },
      });
    return { message: body.remove ? "Member removed" : "Member added" };
  }
  // Scopes
  if (resource === "scopes" && id && method === "DELETE") {
    const [userId, scopeId] = id.split("~");
    await call(token, "DELETE", `users/${userId}/scopes/${scopeId}`);
    return { message: "Scope revoked" };
  }
  // Access requests
  if (resource === "access-requests" && method === "POST") {
    const d = await directory(token);
    if (!id) {
      const request = await call(token, "POST", "access-requests", {
        body: await toRequestBody(token, body.change, body.justification),
      });
      return {
        message: "Access request submitted for independent review",
        request: (await toRequests(token, [request], d))[0],
      };
    }
    if (action !== "approve" && action !== "reject")
      throw new ApiError(404, "Unknown decision");
    await call(token, "POST", `access-requests/${id}/${action}`, {
      body: { comment: body.comment || undefined },
    });
    return {
      message:
        action === "approve"
          ? "Approved access applied and audited"
          : "Request rejected and audited",
    };
  }
  throw new ApiError(404, "Endpoint not available");
}
