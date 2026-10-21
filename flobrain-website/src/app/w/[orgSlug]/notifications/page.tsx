import { NotificationsScreen } from "@/components/v2/screens/NotificationsScreen";

export default async function NotificationsPage({ params }: { params: Promise<{ orgSlug: string }> }) {
  const { orgSlug } = await params;
  return <NotificationsScreen orgSlug={orgSlug} />;
}
