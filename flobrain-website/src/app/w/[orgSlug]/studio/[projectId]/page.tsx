"use client";

import { useParams } from "next/navigation";

import { ProjectEditor } from "@/components/v2/studio/ProjectEditor";

export default function StudioProjectPage() {
  const { orgSlug, projectId } = useParams<{ orgSlug: string; projectId: string }>();
  return <ProjectEditor key={projectId} orgSlug={orgSlug} projectId={projectId} />;
}
