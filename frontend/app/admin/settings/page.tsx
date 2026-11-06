import { Authorized } from "@/components/auth/authorized";
import { SettingsPage } from "@/features/catalog/settings-page";
export default function Page() {
  return (
    <Authorized permission="iam.role.read">
      <SettingsPage />
    </Authorized>
  );
}
