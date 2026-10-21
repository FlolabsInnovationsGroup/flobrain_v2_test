"use client";

import { Empty, ErrorState, Loading, NoAccess } from "@/components/v2/states";
import { useTr } from "@/i18n/phrases";
import type { ScreenState } from "@/lib/v2/screens/status";

export function ScreenBody({
  state,
  error,
  emptyLabel,
  onRetry,
  children,
}: {
  state: ScreenState;
  error?: string | null;
  emptyLabel?: string;
  onRetry?: () => void;
  children: React.ReactNode;
}) {
  const tr = useTr();
  if (state === "loading") return <Loading />;
  if (state === "no-access") return <NoAccess />;
  if (state === "error") return <ErrorState message={error || tr("Something went wrong")} onRetry={onRetry} />;
  if (state === "empty") return <Empty label={emptyLabel} />;
  if (state === "off") {
    return (
      <div className="p-6 text-[color:var(--fb-v2-text-muted)]">
        {tr("This feature is switched off for your organization. An admin can turn it on.")}
      </div>
    );
  }
  return <>{children}</>;
}
