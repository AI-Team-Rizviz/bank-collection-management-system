import type { Session } from "@/lib/api/types";
export function can(session: Session, permission: string) {
  return session.permissions.includes(permission);
}
export const routePermissions: Record<string, string> = {
  dashboard: "iam.user.read",
  users: "iam.user.read",
  roles: "iam.role.read",
  permissions: "iam.permission.read",
  teams: "iam.team.read",
  "access-scopes": "iam.user.read",
  "access-requests": "iam.access.request",
  "audit-logs": "iam.audit.read",
  settings: "iam.role.read",
};
export function mockEnabled(env = process.env) {
  return (
    (env.NODE_ENV === "development" && env.IAM_ADAPTER === "mock") ||
    (env.NODE_ENV === "test" && env.IAM_ADAPTER === "mock")
  );
}
