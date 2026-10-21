import { ToolsScreen } from "@/components/v2/screens/ToolsScreen";

export default async function ToolsPage({ params }: { params: Promise<{ orgSlug: string }> }) {
  const { orgSlug } = await params;
  return <ToolsScreen orgSlug={orgSlug} />;
}
