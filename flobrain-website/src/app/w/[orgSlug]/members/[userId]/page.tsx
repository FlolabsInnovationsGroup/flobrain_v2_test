import { MemberProfileScreen } from "@/components/v2/screens/MemberProfileScreen";

export default async function MemberProfilePage({
  params,
}: {
  params: Promise<{ orgSlug: string; userId: string }>;
}) {
  const { orgSlug, userId } = await params;
  return <MemberProfileScreen orgSlug={orgSlug} userId={userId} />;
}
