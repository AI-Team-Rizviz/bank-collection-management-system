import { Authorized } from "@/components/auth/authorized";
import { UserDetail } from "@/features/users/user-detail";
export default async function Page({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <Authorized permission="iam.user.read">
      <UserDetail id={id} />
    </Authorized>
  );
}
