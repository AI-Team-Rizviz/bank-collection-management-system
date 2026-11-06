import { Authorized } from "@/components/auth/authorized";
import { RequestsPage } from "@/features/access-requests/requests-page";
export default function Page() {
  return (
    <Authorized permission="iam.access.request">
      <RequestsPage />
    </Authorized>
  );
}
