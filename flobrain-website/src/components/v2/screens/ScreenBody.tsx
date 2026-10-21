import { Empty, ErrorState, Loading, NoAccess } from "@/components/v2/states";
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
  if (state === "loading") return <Loading />;
  if (state === "no-access") return <NoAccess />;
  if (state === "error") return <ErrorState message={error || "Something went wrong"} onRetry={onRetry} />;
  if (state === "empty") return <Empty label={emptyLabel} />;
  return <>{children}</>;
}
