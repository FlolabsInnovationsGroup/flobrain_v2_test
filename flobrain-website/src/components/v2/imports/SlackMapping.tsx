"use client";

import { useMemo, useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Badge, Notice, Section } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";

import { dateRange, defaultMapping, mappingToSend, selectedMessages } from "./logic";
import type { ChannelChoice, Meta, Run, SlackChannel, SlackMapping as Mapping } from "./types";

type Props = { run: Run; meta: Meta; busy: boolean; onStart: (mapping: Mapping) => void; onDiscard: () => void };

const KIND_LABEL: Record<SlackChannel["kind"], string> = {
  public: "Public channel",
  private: "Private channel",
  dm: "Direct message",
  group_dm: "Group message",
};

/** Step 2 for Slack: what is in the export, who was matched, and where each channel goes. */
export function SlackMapping({ run, meta, busy, onStart, onDiscard }: Props) {
  const tr = useTr();
  const preview = run.preview ?? {};
  const channels = useMemo(() => preview.channels ?? [], [preview.channels]);
  const people = preview.people ?? [];
  const [mapping, setMapping] = useState<Mapping>(() => defaultMapping(preview, meta.teams));
  const [showPeople, setShowPeople] = useState(false);
  const toSend = mappingToSend(mapping, channels);
  const count = selectedMessages(mapping, channels);
  const matched = people.filter((p) => p.matched).length;

  const setChoice = (id: string, choice: ChannelChoice) => setMapping((m) => ({ ...m, channels: { ...m.channels, [id]: choice } }));
  const visible = channels.filter((c) => (c.kind === "private" ? mapping.include_private : c.kind === "public" ? true : mapping.include_dms));

  return (
    <Section title={tr("Check and choose")} aside={<Badge tone="accent">{tr("Step 2 of 3")}</Badge>}>
      <div className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
        <dl className="mb-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
          <Stat label={tr("Channels")} value={channels.length} />
          <Stat label={tr("Messages")} value={Number(preview.totals?.messages ?? 0)} />
          <Stat label={tr("People matched")} value={`${matched} / ${people.length}`} />
          <Stat label={tr("Dates")} value={dateRange(String(preview.totals?.first ?? ""), String(preview.totals?.last ?? ""))} />
        </dl>

        <p className="mb-3 text-sm text-[color:var(--fb-v2-text-muted)]">
          {tr("People are matched by email to members of this workspace. Messages from anyone else show as “Imported: Name”.")}{" "}
          <button type="button" className="underline underline-offset-2" onClick={() => setShowPeople((v) => !v)} aria-expanded={showPeople}>
            {showPeople ? tr("Hide people") : tr("Show people")}
          </button>
        </p>
        {showPeople ? (
          <ul className="mb-4 grid gap-1 text-sm sm:grid-cols-2">
            {people.map((p) => (
              <li key={p.slack_id} className="flex flex-wrap items-center gap-2">
                <span className="min-w-0 truncate">{p.name}</span>
                {p.matched ? <Badge tone="good">{tr("Matched: {name}", { name: p.member_name })}</Badge> : <Badge>{tr("Imported: {name}", { name: p.name })}</Badge>}
              </li>
            ))}
          </ul>
        ) : null}

        <fieldset className="mb-4 space-y-2 text-sm">
          <legend className="mb-1 font-medium">{tr("What to include")}</legend>
          {preview.has_private ? (
            <label className="flex items-start gap-2">
              <input type="checkbox" className="mt-1" checked={mapping.include_private} onChange={(e) => setMapping((m) => ({ ...m, include_private: e.target.checked }))} />
              <span>{tr("Private channels. Each becomes a private room for the matched people only.")}</span>
            </label>
          ) : null}
          {preview.has_dms ? (
            <label className="flex items-start gap-2">
              <input type="checkbox" className="mt-1" checked={mapping.include_dms} onChange={(e) => setMapping((m) => ({ ...m, include_dms: e.target.checked }))} />
              <span>{tr("Direct messages. Only include them if everyone agreed.")}</span>
            </label>
          ) : null}
          <label className="flex items-start gap-2">
            <input type="checkbox" className="mt-1" checked={mapping.include_bots} onChange={(e) => setMapping((m) => ({ ...m, include_bots: e.target.checked }))} />
            <span>{tr("Messages from bots and apps")}</span>
          </label>
        </fieldset>

        <h3 className="mb-2 text-sm font-medium">{tr("Where each channel goes")}</h3>
        <ul className="divide-y divide-[color:var(--fb-v2-border)]">
          {visible.map((c) => (
            <ChannelRow key={c.id} channel={c} choice={mapping.channels[c.id] ?? { target: "skip" }} meta={meta} onChange={(ch) => setChoice(c.id, ch)} />
          ))}
        </ul>

        <p className="mt-4 text-sm text-[color:var(--fb-v2-text-muted)]">
          {tr("Messages keep their original time and author. Files stay in Slack: messages link to them. You can undo the whole import later.")}
        </p>
        <div className="mt-4 flex flex-wrap justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onDiscard} disabled={busy}>
            {tr("Discard")}
          </Button>
          <Button type="button" onClick={() => onStart(toSend)} disabled={busy || !Object.keys(toSend.channels).length}>
            {tr("Import {n} messages", { n: count.toLocaleString() })}
          </Button>
        </div>
        {!meta.is_admin ? <Notice>{tr("Only an org owner or admin can create new teams.")}</Notice> : null}
      </div>
    </Section>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-[color:var(--fb-v2-text-muted)]">{label}</dt>
      <dd className="v2-mono truncate text-base">{typeof value === "number" ? value.toLocaleString() : value || "–"}</dd>
    </div>
  );
}

function ChannelRow({ channel: c, choice, meta, onChange }: { channel: SlackChannel; choice: ChannelChoice; meta: Meta; onChange: (c: ChannelChoice) => void }) {
  const tr = useTr();
  const id = `dest-${c.id}`;
  const value = choice.target === "team" ? `team:${choice.team_id ?? ""}` : choice.target;
  return (
    <li className="flex flex-wrap items-center justify-between gap-3 py-3">
      <div className="min-w-0 flex-1 basis-56">
        <p className="truncate font-medium">{c.kind === "public" || c.kind === "private" ? `#${c.name}` : c.name}</p>
        <p className="text-xs text-[color:var(--fb-v2-text-muted)]">
          {tr(KIND_LABEL[c.kind])} · {tr("{n} messages", { n: c.messages.toLocaleString() })} · {tr("{m} of {n} people matched", { m: c.matched, n: c.members })}
          {c.archived ? ` · ${tr("Archived")}` : ""}
        </p>
        {c.kind !== "public" && c.matched === 0 ? <p className="text-xs text-[color:var(--fb-v2-error)]">{tr("Nobody here is matched, so it will be skipped.")}</p> : null}
      </div>
      <label htmlFor={id} className="sr-only">
        {tr("Destination for {name}", { name: c.name })}
      </label>
      <select
        id={id}
        className="v2-input w-full sm:w-64"
        value={value}
        onChange={(e) => {
          const v = e.target.value;
          if (v.startsWith("team:")) onChange({ target: "team", team_id: v.slice(5) });
          else onChange({ target: v as ChannelChoice["target"] });
        }}
      >
        {c.kind === "public" ? (
          <>
            <optgroup label={tr("A team's room")}>
              {meta.teams.map((t) => (
                <option key={t.id} value={`team:${t.id}`}>
                  {t.name}
                </option>
              ))}
            </optgroup>
            {meta.is_admin ? <option value="new_team">{tr("New team named #{name}", { name: c.name })}</option> : null}
          </>
        ) : (
          <option value="private">{tr("Private room, matched people only")}</option>
        )}
        <option value="skip">{tr("Don't import")}</option>
      </select>
    </li>
  );
}
