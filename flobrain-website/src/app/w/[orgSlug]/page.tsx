import { CockpitScreen } from "@/components/v2/screens/CockpitScreen";

export default async function CockpitPage({ params }: { params: Promise<{ orgSlug: string }> }) {
  const { orgSlug } = await params;
  return <CockpitScreen orgSlug={orgSlug} />;
}
