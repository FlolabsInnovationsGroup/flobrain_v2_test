import { DocsScreen } from "@/components/v2/screens/DocsScreen";

export default async function RoomDocsPage({
  params,
}: {
  params: Promise<{ orgSlug: string; roomId: string }>;
}) {
  const { orgSlug, roomId } = await params;
  return <DocsScreen orgSlug={orgSlug} roomId={roomId} />;
}
