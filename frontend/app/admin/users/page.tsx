import { Authorized } from "@/components/auth/authorized";
import { Suspense } from "react";
import { UsersPage } from "@/features/users/users-page";
export default function Page() {
  return (
    <Authorized permission="iam.user.read">
      <Suspense
        fallback={<div className="loading-state">Loading user filters…</div>}
      >
        <UsersPage />
      </Suspense>
    </Authorized>
  );
}
