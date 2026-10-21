import { DocsScreen } from "@/components/v2/screens/DocsScreen";

export default async function RoomDocPage({
  params,
}: {
  params: Promise<{ orgSlug: string; roomId: string; docId: string }>;
}) {
  const { orgSlug, roomId, docId } = await params;
  return <DocsScreen orgSlug={orgSlug} roomId={roomId} initialDocId={docId} />;
}
