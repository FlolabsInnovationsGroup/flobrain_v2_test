import { ReportsScreen } from "@/components/v2/screens/ReportsScreen";

export default async function ReportsPage({ params }: { params: Promise<{ orgSlug: string }> }) {
  const { orgSlug } = await params;
  return <ReportsScreen orgSlug={orgSlug} />;
}
