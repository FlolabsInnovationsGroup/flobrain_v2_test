import { RoomsIndexScreen } from "@/components/v2/rooms/RoomsIndexScreen";

export default async function RoomsPage({
  params,
  searchParams,
}: {
  params: Promise<{ orgSlug: string }>;
  searchParams: Promise<{ new?: string }>;
}) {
  const { orgSlug } = await params;
  const { new: mode } = await searchParams;
  return <RoomsIndexScreen orgSlug={orgSlug} initialMode={mode === "dm" || mode === "group" ? mode : ""} />;
}
