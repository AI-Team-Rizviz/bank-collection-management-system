import { Authorized } from "@/components/auth/authorized";
import { TeamsPage } from "@/features/teams/teams-page";
export default function Page() {
  return (
    <Authorized permission="iam.team.read">
      <TeamsPage />
    </Authorized>
  );
}
