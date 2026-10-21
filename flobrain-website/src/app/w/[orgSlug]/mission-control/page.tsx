import { MissionControlScreen } from "@/components/v2/screens/MissionControlScreen";

export default async function MissionControlPage({ params }: { params: Promise<{ orgSlug: string }> }) {
  const { orgSlug } = await params;
  return <MissionControlScreen orgSlug={orgSlug} />;
}
