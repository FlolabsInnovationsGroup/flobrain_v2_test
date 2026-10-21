"use client";

import { useTr } from "@/i18n/phrases";

export function ErrorState({
  message,
  onRetry,
  retryLabel,
}: {
  message: string;
  onRetry?: () => void;
  retryLabel?: string;
}) {
  const tr = useTr();
  return (
    <div className="p-6" role="alert">
      <p className="text-[color:var(--fb-v2-error)]">{message}</p>
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="mt-3 rounded-[length:var(--fb-v2-radius)] bg-[color:var(--fb-v2-accent)] px-3 py-1.5"
        >
          {retryLabel ?? tr("Retry")}
        </button>
      ) : null}
    </div>
  );
}
