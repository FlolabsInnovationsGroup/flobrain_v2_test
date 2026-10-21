"use client";

import { useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Notice } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";

import { CATEGORIES, categoryLabel, retentionLabel, type Category, type Rules } from "./types";

const RETENTION = [30, 90, 180, 365, 730];

/** The organization's memory rules (memory.manage). Every change is audited. */
export function RulesForm({ rules, onSave }: { rules: Rules; onSave: (next: Partial<Rules>) => Promise<boolean> }) {
  const tr = useTr();
  const [draft, setDraft] = useState<Rules>(rules);
  const [busy, setBusy] = useState(false);
  const newlyBlocked = draft.blocked_categories.filter((c) => !rules.blocked_categories.includes(c));
  const changed = JSON.stringify(draft) !== JSON.stringify(rules);

  function toggleBlocked(category: Category, on: boolean) {
    const next = on ? [...draft.blocked_categories, category] : draft.blocked_categories.filter((c) => c !== category);
    setDraft({ ...draft, blocked_categories: next });
  }

  return (
    <form
      className="flex flex-col gap-4 rounded-xl bg-[color:var(--fb-v2-surface)] p-4 text-sm"
      onSubmit={async (e) => {
        e.preventDefault();
        if (newlyBlocked.length && !window.confirm(tr("Memories in the categories you block are deleted for everyone. Continue?"))) return;
        setBusy(true);
        await onSave({
          enabled: draft.enabled,
          ask_before_saving: draft.ask_before_saving,
          retention_days: draft.retention_days,
          blocked_categories: draft.blocked_categories,
          team_memory: draft.team_memory,
        });
        setBusy(false);
      }}
    >
      <label className="inline-flex items-start gap-2">
        <input type="checkbox" className="mt-1" checked={draft.enabled} onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })} />
        <span>
          <span className="block font-medium">{tr("Buddies can remember things")}</span>
          <span className="text-[color:var(--fb-v2-text-muted)]">{tr("Off: buddies don't save or use memories. People can still see and delete theirs.")}</span>
        </span>
      </label>
      <label className="inline-flex items-start gap-2">
        <input type="checkbox" className="mt-1" checked={draft.ask_before_saving} onChange={(e) => setDraft({ ...draft, ask_before_saving: e.target.checked })} />
        <span>
          <span className="block font-medium">{tr("Ask before saving")}</span>
          <span className="text-[color:var(--fb-v2-text-muted)]">{tr("A buddy asks the person first. Recommended.")}</span>
        </span>
      </label>
      <label className="inline-flex items-start gap-2">
        <input type="checkbox" className="mt-1" checked={draft.team_memory} onChange={(e) => setDraft({ ...draft, team_memory: e.target.checked })} />
        <span>
          <span className="block font-medium">{tr("Team memory")}</span>
          <span className="text-[color:var(--fb-v2-text-muted)]">{tr("Shared notes about a team that buddies use for its members.")}</span>
        </span>
      </label>
      <label className="block">
        <span className="mb-1 block font-medium">{tr("Keep memories for")}</span>
        <select
          className="v2-input w-auto"
          value={draft.retention_days ?? ""}
          onChange={(e) => setDraft({ ...draft, retention_days: e.target.value ? Number(e.target.value) : null })}
        >
          {RETENTION.map((days) => (
            <option key={days} value={days}>
              {retentionLabel(tr, days)}
            </option>
          ))}
          <option value="">{retentionLabel(tr, null)}</option>
        </select>
        <span className="mt-1 block text-[color:var(--fb-v2-text-muted)]">{tr("Counted from the last change. Shorter retention deletes older memories right away.")}</span>
      </label>
      <fieldset>
        <legend className="mb-1 font-medium">{tr("Never remember")}</legend>
        <div className="flex flex-wrap gap-3">
          {CATEGORIES.map((c) => (
            <label key={c} className="inline-flex items-center gap-2">
              <input type="checkbox" checked={draft.blocked_categories.includes(c)} onChange={(e) => toggleBlocked(c, e.target.checked)} />
              {categoryLabel(tr, c)}
            </label>
          ))}
        </div>
        <span className="mt-1 block text-[color:var(--fb-v2-text-muted)]">{tr("Health, beliefs, money, IDs and similar details are never kept, whatever you choose here.")}</span>
      </fieldset>
      {newlyBlocked.length ? <Notice kind="error">{tr("Saving deletes existing memories in: {list}", { list: newlyBlocked.map((c) => categoryLabel(tr, c)).join(", ") })}</Notice> : null}
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={busy || !changed}>
          {tr("Save rules")}
        </Button>
        {changed ? (
          <Button type="button" variant="ghost" onClick={() => setDraft(rules)}>
            {tr("Cancel")}
          </Button>
        ) : null}
        <span className="text-xs text-[color:var(--fb-v2-text-muted)]">{tr("Changes are recorded in the audit log, without anyone's memories.")}</span>
      </div>
    </form>
  );
}
