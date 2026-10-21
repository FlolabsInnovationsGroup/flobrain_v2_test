import { Suspense } from "react";

import { CalendarScreen } from "@/components/v2/screens/CalendarScreen";

export default async function CalendarPage({ params }: { params: Promise<{ orgSlug: string }> }) {
  const { orgSlug } = await params;
  return (
    <Suspense>
      <CalendarScreen orgSlug={orgSlug} />
    </Suspense>
  );
}
