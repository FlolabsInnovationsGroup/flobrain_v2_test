import { AccessScreen } from "@/components/v2/screens/AccessScreen";

export default async function AccessSettingsPage({ params }: { params: Promise<{ orgSlug: string }> }) {
  const { orgSlug } = await params;
  return <AccessScreen orgSlug={orgSlug} />;
}
