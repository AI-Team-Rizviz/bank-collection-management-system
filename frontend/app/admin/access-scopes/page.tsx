import { Authorized } from "@/components/auth/authorized";
import { ScopesPage } from "@/features/catalog/scopes-page";
export default function Page() {
  return (
    <Authorized permission="iam.user.read">
      <ScopesPage />
    </Authorized>
  );
}
