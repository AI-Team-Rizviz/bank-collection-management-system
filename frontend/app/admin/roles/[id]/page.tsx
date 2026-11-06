import { Authorized } from "@/components/auth/authorized";
import { RoleDetail } from "@/features/roles/role-detail";
export default async function Page({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <Authorized permission="iam.role.read">
      <RoleDetail id={id} />
    </Authorized>
  );
}
