"use client";
import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type Resources } from "./client";
import type { ListParams } from "./types";
export function useList<K extends keyof Resources>(
  resource: K,
  params: ListParams = {},
) {
  const [search, setSearch] = useState(params.search);
  useEffect(() => {
    const timer = setTimeout(() => setSearch(params.search), 250);
    return () => clearTimeout(timer);
  }, [params.search]);
  const effectiveParams = { ...params, search };
  return useQuery({
    queryKey: ["iam", resource, effectiveParams],
    queryFn: ({ signal }) => api.list(resource, effectiveParams, signal),
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
