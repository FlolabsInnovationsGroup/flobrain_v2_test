import { HomeScreen } from "@/components/v2/screens/HomeScreen";

export default async function HomePage({ params }: { params: Promise<{ orgSlug: string }> }) {
  const { orgSlug } = await params;
  return <HomeScreen orgSlug={orgSlug} />;
}
