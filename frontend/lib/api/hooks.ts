"use client";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type Resources } from "./client";
import type { ListParams } from "./types";
export function useList<K extends keyof Resources>(
  resource: K,
  params: ListParams = {},
) {
  return useQuery({
    queryKey: ["iam", resource, params],
    queryFn: ({ signal }) => api.list(resource, params, signal),
    placeholderData: (previous) => previous,
  });
}
export function useDashboard() {
  return useQuery({
    queryKey: ["iam", "dashboard"],
    queryFn: ({ signal }) => api.dashboard(signal),
  });
}
export function useUser(id: string) {
  return useQuery({
    queryKey: ["iam", "users", id],
    queryFn: ({ signal }) => api.user(id, signal),
  });
}
export function useRole(id: string) {
  return useQuery({
    queryKey: ["iam", "roles", id],
    queryFn: ({ signal }) => api.role(id, signal),
  });
}
export function useChange() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({
      path,
      body,
      method,
    }: {
      path: string;
      body?: unknown;
      method?: string;
    }) => api.mutate(path, body, method),
    onSuccess: () => client.invalidateQueries({ queryKey: ["iam"] }),
  });
}
