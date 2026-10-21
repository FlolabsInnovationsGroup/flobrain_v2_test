import { SearchScreen } from "@/components/v2/screens/SearchScreen";

export default async function SearchPage({ params }: { params: Promise<{ orgSlug: string }> }) {
  const { orgSlug } = await params;
  return <SearchScreen orgSlug={orgSlug} />;
}
