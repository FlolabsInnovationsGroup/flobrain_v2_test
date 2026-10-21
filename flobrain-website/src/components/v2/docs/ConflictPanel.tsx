"use client";

import { Button } from "@/components/v2/ui/button";
import { when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import type { DocRow } from "@/lib/v2/screens/docs";

export type ConflictChoice = "mine" | "theirs" | "merge";

/** Someone saved first. Show both versions side by side; the person's draft is never thrown away unasked. */
export function ConflictPanel({
  mine,
  theirs,
  onChoose,
}: {
  mine: { title: string; text: string };
  theirs: DocRow;
  onChoose: (choice: ConflictChoice) => void;
}) {
  const tr = useTr();
  const who = theirs.updated_by?.name ?? tr("someone");
  return (
    <section
      role="alert"
      aria-label={tr("Edit conflict")}
      className="mb-4 rounded-xl p-4 ring-1 ring-inset ring-[color:var(--fb-v2-waiting)]"
    >
      <h3 className="font-semibold">
        {tr("{name} saved a newer version while you were editing", { name: who })}
      </h3>
      <p className="mt-1 text-sm text-[color:var(--fb-v2-text-muted)]">
        {tr(
          "Your draft is safe in this browser. Choose which version to keep, or keep both and combine them by hand."
        )}
      </p>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <figure className="min-w-0">
          <figcaption className="mb-1 text-sm font-medium">{tr("Your draft")}</figcaption>
          <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-lg p-3 text-sm ring-1 ring-inset ring-[color:var(--fb-v2-border)]">
            {mine.text}
          </pre>
        </figure>
        <figure className="min-w-0">
          <figcaption className="mb-1 text-sm font-medium">
            {tr("Saved version {n}, {when} by {name}", {
              n: theirs.version,
              when: when(theirs.updated_at),
              name: who,
            })}
          </figcaption>
          <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-lg p-3 text-sm ring-1 ring-inset ring-[color:var(--fb-v2-border)]">
            {theirs.content_text}
          </pre>
        </figure>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button type="button" onClick={() => onChoose("mine")}>
          {tr("Keep my draft")}
        </Button>
        <Button type="button" variant="outline" onClick={() => onChoose("merge")}>
          {tr("Combine by hand")}
        </Button>
        <Button type="button" variant="ghost" onClick={() => onChoose("theirs")}>
          {tr("Use the saved version")}
        </Button>
      </div>
    </section>
  );
}
