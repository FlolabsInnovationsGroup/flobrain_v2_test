import { TimeScreen } from "@/components/v2/screens/TimeScreen";

export default async function TimePage({ params }: { params: Promise<{ orgSlug: string }> }) {
  const { orgSlug } = await params;
  return <TimeScreen orgSlug={orgSlug} />;
}
