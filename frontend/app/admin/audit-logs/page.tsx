import { Authorized } from "@/components/auth/authorized";
import { AuditPage } from "@/features/audit/audit-page";
export default function Page() {
  return (
    <Authorized permission="iam.audit.read">
      <AuditPage />
    </Authorized>
  );
}
