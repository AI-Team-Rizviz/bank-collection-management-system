import { getSession } from "@/lib/auth/server";
import { Providers } from "@/app/providers";
import { AdminShell } from "@/components/layout/admin-shell";
export default async function AdminLayout({children}:{children:React.ReactNode}) {const session=await getSession();if(!session)return <main className="auth-screen"><div className="brand-mark">C</div><h1>Connect your enterprise identity</h1><p>This workspace requires a verified IAM session.</p><p>OIDC login is awaiting your identity provider integration. Production access is disabled until it is connected.</p><a href="/">Return to application</a></main>;return <Providers session={session}><AdminShell>{children}</AdminShell></Providers>;}
