"use client";

import { useTr } from "@/i18n/phrases";

import { neverLabel, retentionLabel, type Rules } from "./types";

/** Plain words: what is kept, why, who sees it, and what is never kept. */
export function Explainer({ rules, never }: { rules: Rules; never: string[] }) {
  const tr = useTr();
  return (
    <details className="mb-6 rounded-xl bg-[color:var(--fb-v2-surface)] p-4 text-sm" open>
      <summary className="cursor-pointer font-medium">{tr("What buddies remember, and why")}</summary>
      <div className="mt-3 grid gap-4 md:grid-cols-2">
        <ul className="list-disc space-y-1 ps-5">
          <li>{tr("Short notes about how you like to work: your preferences, your role, your projects and who you work with.")}</li>
          <li>{tr("Buddies use them so you don't have to repeat yourself. They are added to a chat as notes, never as instructions.")}</li>
          <li>
            {rules.ask_before_saving
              ? tr("A buddy asks before it saves anything. You answer yes or no in the chat or here.")
              : tr("Your organization lets buddies save notes without asking. The buddy tells you when it does.")}
          </li>
          <li>{tr("Only you can see your notes. Admins can't read them. Team notes are visible to the team.")}</li>
          <li>{retentionLabel(tr, rules.retention_days)}</li>
          <li>{tr("In any chat you can say “remember that…”, “forget…” or “what do you remember about me”.")}</li>
        </ul>
        <div>
          <p className="font-medium">{tr("Never kept, even if you ask")}</p>
          <ul className="mt-1 flex flex-wrap gap-1">
            {[...never.map((key) => neverLabel(tr, key)), tr("Emails and phone numbers")].map((label) => (
              <li key={label} className="rounded-full bg-[color:var(--fb-v2-border)] px-2 py-0.5 text-xs">
                {label}
              </li>
            ))}
          </ul>
          <p className="mt-2 text-[color:var(--fb-v2-text-muted)]">{tr("If a buddy picks up something like this, it is dropped before anything is saved.")}</p>
        </div>
      </div>
    </details>
  );
}
