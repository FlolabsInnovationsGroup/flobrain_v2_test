import { TimeReports } from "@/components/v2/timer/TimeReports";

export default async function TimeReportsPage({ params }: { params: Promise<{ orgSlug: string }> }) {
  const { orgSlug } = await params;
  return <TimeReports orgSlug={orgSlug} />;
}
