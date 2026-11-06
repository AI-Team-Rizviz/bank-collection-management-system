import { getSession } from "@/lib/auth/server";
import { can } from "@/lib/auth/policy";
import { ShieldCheck } from "lucide-react";
/** Server-side page gate; IAM separately authorizes every API read and mutation. */
export async function Authorized({
  permission,
  children,
}: {
  permission: string;
  children: React.ReactNode;
}) {
  const session = await getSession();
  if (!session || !can(session, permission))
    return (
      <div className="error-state">
        <ShieldCheck />
        <h1>Access restricted</h1>
        <p>Your verified session does not authorize this workspace.</p>
      </div>
    );
  return <>{children}</>;
}
