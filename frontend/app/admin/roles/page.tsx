import { Authorized } from "@/components/auth/authorized";
import { RolesPage } from "@/features/roles/roles-page";
export default function Page() {
  return (
    <Authorized permission="iam.role.read">
      <RolesPage />
    </Authorized>
  );
}
