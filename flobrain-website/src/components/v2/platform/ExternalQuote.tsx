"use client";

import { Badge } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";

export type External = { text: string; is_error: boolean; untrusted: boolean; instructions_ignored: boolean; redacted: boolean; notice: string };

/**
 * Text from an external agent. It is quoted data, never FloBrain's own words: shown in a
 * quote block with where it came from, and a warning when it tries to give instructions.
 */
export function ExternalQuote({ source, external }: { source: string; external: External }) {
  const tr = useTr();
  return (
    <figure className="mt-2 rounded-lg bg-[color:var(--fb-v2-page)] p-3 ring-1 ring-inset ring-[color:var(--fb-v2-border)]">
      <figcaption className="mb-2 flex flex-wrap items-center gap-2 text-xs text-[color:var(--fb-v2-text-muted)]">
        <Badge tone="waiting">{tr("External, not checked")}</Badge>
        <span>{tr("From {source}", { source })}</span>
        {external.redacted ? <Badge>{tr("Personal data removed before sending")}</Badge> : null}
        {external.is_error ? <Badge tone="bad">{tr("The agent reported an error")}</Badge> : null}
      </figcaption>
      <blockquote className="whitespace-pre-wrap break-words border-s-2 border-[color:var(--fb-v2-border)] ps-3 text-sm">{external.text || tr("(no text)")}</blockquote>
      {external.instructions_ignored ? (
        <p role="status" className="mt-2 text-sm font-medium text-[color:var(--fb-v2-error)]">
          {tr("This text tries to give instructions. FloBrain did not follow them and nothing was changed.")}
        </p>
      ) : null}
      <p className="mt-1 text-xs text-[color:var(--fb-v2-text-muted)]">{tr("FloBrain shows this as quoted data. Any action it suggests still needs your approval.")}</p>
    </figure>
  );
}
