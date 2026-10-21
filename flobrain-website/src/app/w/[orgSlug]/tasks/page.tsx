import { Suspense } from "react";

import { TasksScreen } from "@/components/v2/screens/TasksScreen";

export default async function TasksPage({ params }: { params: Promise<{ orgSlug: string }> }) {
  const { orgSlug } = await params;
  return (
    <Suspense>
      <TasksScreen orgSlug={orgSlug} />
    </Suspense>
  );
}
