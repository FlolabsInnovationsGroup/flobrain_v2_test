import { MeetingsScreen } from "@/components/v2/screens/MeetingsScreen";

export default async function RoomMeetingsPage({
  params,
}: {
  params: Promise<{ orgSlug: string; roomId: string }>;
}) {
  const { orgSlug, roomId } = await params;
  return <MeetingsScreen orgSlug={orgSlug} roomId={roomId} />;
}
