"use client";

import { useParams } from "next/navigation";
import { Suspense } from "react";

import { StudioHub } from "@/components/v2/studio/StudioHub";

export default function StudioPage() {
  const { orgSlug } = useParams<{ orgSlug: string }>();
  return (
    <Suspense>
      <StudioHub orgSlug={orgSlug} />
    </Suspense>
  );
}
