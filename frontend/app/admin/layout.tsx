import { Suspense } from "react";
import { connection } from "next/server";
import Link from "next/link";
import { getSession } from "@/lib/auth/server";
import { Providers } from "@/app/providers";
import { AdminShell } from "@/components/layout/admin-shell";
async function AuthenticatedAdmin({ children }: { children: React.ReactNode }) {
  await connection();
  const session = await getSession();
  if (!session)
    return (
      <main className="auth-screen">
        <div className="brand-mark">C</div>
        <h1>Connect your enterprise identity</h1>
        <p>This workspace requires a verified IAM session.</p>
        <p>
          OIDC login is awaiting your identity provider integration. Production
          access is disabled until it is connected.
        </p>
        <Link href="/">Return to application</Link>
      </main>
    );
  return (
    <Providers session={session}>
      <AdminShell>{children}</AdminShell>
    </Providers>
  );
}

export default function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <Suspense
      fallback={
        <main className="loading-state" role="status">
          Verifying IAM session…
        </main>
      }
    >
      <AuthenticatedAdmin>{children}</AuthenticatedAdmin>
    </Suspense>
  );
}
