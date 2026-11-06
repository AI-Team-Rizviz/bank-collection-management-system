"use client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createContext, useContext, useState } from "react";
import type { Session } from "@/lib/api/types";
const SessionContext = createContext<Session | null>(null);
export function useSession() {
  const session = useContext(SessionContext);
  if (!session) throw new Error("Session provider missing");
  return session;
}
export function Providers({
  children,
  session,
}: {
  children: React.ReactNode;
  session: Session;
}) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { staleTime: 30000, retry: 1, refetchOnWindowFocus: false },
        },
      }),
  );
  return (
    <SessionContext value={session}>
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    </SessionContext>
  );
}
