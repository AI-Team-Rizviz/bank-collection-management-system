import { Authorized } from "@/components/auth/authorized";
import { Dashboard } from "@/features/dashboard/dashboard";
export default function Page() {
  return (
    <Authorized permission="iam.user.read">
      <Dashboard />
    </Authorized>
  );
}
