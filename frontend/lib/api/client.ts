import type {
  ListParams,
  Page,
  User,
  Role,
  Team,
  Permission,
  Scope,
  AccessRequest,
  AuditEvent,
  Dashboard,
  UserDetails,
  RoleDetails,
  Settings,
  MutationResult,
} from "./types";
import { ApiError } from "./error";
const BASE = "/api/v1";
export async function request<T>(
  path: string,
  options: {
    method?: string;
    body?: unknown;
    params?: ListParams;
    signal?: AbortSignal;
  } = {},
): Promise<T> {
  const query = new URLSearchParams();
  Object.entries(options.params ?? {}).forEach(([k, v]) => {
    if (v !== undefined && v !== "") query.set(k, String(v));
  });
  const response = await fetch(
    `${BASE}/${path}${query.size ? `?${query}` : ""}`,
    {
      method: options.method ?? "GET",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body:
        options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal
        ? AbortSignal.any([options.signal, AbortSignal.timeout(20000)])
        : AbortSignal.timeout(20000),
    },
  ).catch((error) => {
    if (error.name === "AbortError") throw error;
    throw new ApiError(
      0,
      "Unable to reach IAM. Check your connection and retry.",
    );
  });
  const data = await response.json().catch(() => null);
  if (!response.ok)
    throw new ApiError(
      response.status,
      data?.message ?? "The request could not be completed",
    );
  return data as T;
}
export interface Resources {
  users: User;
  roles: Role;
  teams: Team;
  permissions: Permission;
  scopes: Scope;
  "access-requests": AccessRequest;
  "audit-logs": AuditEvent;
}
export const api = {
  list: <K extends keyof Resources>(
    resource: K,
    params: ListParams,
    signal?: AbortSignal,
  ) => request<Page<Resources[K]>>(resource, { params, signal }),
  dashboard: (signal?: AbortSignal) =>
    request<Dashboard>("dashboard", { signal }),
  user: (id: string, signal?: AbortSignal) =>
    request<UserDetails>(`users/${id}`, { signal }),
  role: (id: string, signal?: AbortSignal) =>
    request<RoleDetails>(`roles/${id}`, { signal }),
  settings: (signal?: AbortSignal) => request<Settings>("settings", { signal }),
  mutate: (path: string, body?: unknown, method = "POST") =>
    request<MutationResult>(path, { method, body }),
};
