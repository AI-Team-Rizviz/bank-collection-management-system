import { RoleDetail } from "@/features/roles/role-detail";
export default async function Page({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <RoleDetail id={id} />;
}
