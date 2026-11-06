export type UserStatus =
  "ACTIVE" | "INACTIVE" | "SUSPENDED" | "PENDING_ACTIVATION";
export type ScopeType =
  "OWN" | "TEAM" | "BRANCH" | "REGION" | "PORTFOLIO" | "GLOBAL";
export interface Scope {
  id: string;
  userId: string;
  roleId: string;
  type: ScopeType;
  reference: string;
  region: string;
}
export interface User {
  id: string;
  name: string;
  username: string;
  email: string;
  employeeReference: string;
  roleIds: string[];
  teamId: string;
  region: string;
  status: UserStatus;
  lastLogin?: string;
  createdAt: string;
}
export interface Role {
  id: string;
  name: string;
  code: string;
  description: string;
  permissions: string[];
  privileged: boolean;
  system: boolean;
  phase: "MVP" | "FUTURE";
  status: "ACTIVE" | "INACTIVE";
  userCount: number;
}
export interface Permission {
  id: string;
  code: string;
  description: string;
  module: string;
  action: string;
  sensitive: boolean;
  roleIds: string[];
}
export interface Team {
  id: string;
  name: string;
  code: string;
  supervisorId: string;
  memberIds: string[];
  branch: string;
  region: string;
  status: "ACTIVE" | "INACTIVE";
  createdAt: string;
}
export type Change =
  | { kind: "ASSIGN_ROLE"; userId: string; roleId: string }
  | { kind: "REVOKE_ROLE"; userId: string; roleId: string }
  | {
      kind: "GRANT_SCOPE";
      userId: string;
      roleId: string;
      scopeType: ScopeType;
      reference: string;
    }
  | { kind: "GRANT_ROLE_PERMISSION"; roleId: string; permission: string }
  | { kind: "REVOKE_ROLE_PERMISSION"; roleId: string; permission: string }
  | { kind: "DEACTIVATE_USER"; userId: string };
export interface AccessRequest {
  id: string;
  change: Change;
  target: string;
  requestedBy: string;
  requesterName: string;
  submittedAt: string;
  status: "PENDING" | "APPLIED" | "REJECTED";
  risk: "Standard" | "High";
  justification: string;
  existingAccess: string[];
  proposedAccess: string;
  history: { actor: string; decision: string; comment: string; at: string }[];
}
export interface AuditEvent {
  id: string;
  timestamp: string;
  actor: string;
  action: string;
  target: string;
  result: "SUCCESS" | "DENIED" | "FAILURE";
  source: string;
  description: string;
}
export interface Session {
  id: string;
  name: string;
  email: string;
  role: string;
  permissions: string[];
  regions: string[];
  mock: boolean;
}
export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
}
export interface ListParams {
  page?: number;
  pageSize?: number;
  search?: string;
  status?: string;
  role?: string;
  team?: string;
  module?: string;
  actor?: string;
  action?: string;
  result?: string;
  from?: string;
  to?: string;
  sort?: string;
  direction?: "asc" | "desc";
}
export interface Dashboard {
  totalUsers: number;
  activeUsers: number;
  inactiveUsers: number;
  totalRoles: number;
  pendingRequests: number;
  activeTeams: number;
  statuses: { status: UserStatus; count: number }[];
  requests: AccessRequest[];
  activity: AuditEvent[];
}
export interface UserDetails {
  user: User;
  roles: Role[];
  permissions: string[];
  scopes: Scope[];
  teams: Team[];
  audit: AuditEvent[];
}
export interface RoleDetails {
  role: Role;
  users: User[];
  permissions: Permission[];
  audit: AuditEvent[];
}
export interface MutationResult {
  message: string;
  request?: AccessRequest;
  user?: User;
}
export interface Settings {
  identityProvider: string;
  sessionPolicy: string;
  approvalPolicy: string;
  reviewPeriod: string;
  catalog: string;
}
