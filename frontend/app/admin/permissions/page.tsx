import { Authorized } from "@/components/auth/authorized";
import { PermissionsPage } from "@/features/catalog/permissions-page";
export default function Page() {
  return (
    <Authorized permission="iam.permission.read">
      <PermissionsPage />
    </Authorized>
  );
}
