import { RoomAIScreen } from "@/components/v2/rooms/RoomAIScreen";

export default async function RoomAIPage({
  params,
}: {
  params: Promise<{ orgSlug: string; roomId: string }>;
}) {
  const { orgSlug, roomId } = await params;
  return <RoomAIScreen orgSlug={orgSlug} roomId={roomId} />;
}
