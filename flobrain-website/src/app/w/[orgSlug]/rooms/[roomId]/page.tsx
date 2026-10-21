import { ChatScreen } from "@/components/v2/screens/ChatScreen";

export default async function RoomChatPage({
  params,
}: {
  params: Promise<{ orgSlug: string; roomId: string }>;
}) {
  const { orgSlug, roomId } = await params;
  return <ChatScreen orgSlug={orgSlug} roomId={roomId} />;
}
