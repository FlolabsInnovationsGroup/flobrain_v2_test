import { DirectoryScreen } from "@/components/v2/screens/DirectoryScreen";

export default async function DirectoryPage({ params }: { params: Promise<{ orgSlug: string }> }) {
  const { orgSlug } = await params;
  return <DirectoryScreen orgSlug={orgSlug} />;
}
