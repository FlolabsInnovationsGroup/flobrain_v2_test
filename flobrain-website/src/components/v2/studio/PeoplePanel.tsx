"use client";

import { useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Badge, Notice } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { has } from "@/lib/v2/access";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText, rowsOf } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

import type { Member, People } from "./model";

/** Who appears in a recording, and whether each person consented to public posts. */
export function PeoplePanel({ orgId, assetId, onChange }: { orgId: string | null; assetId: string; onChange?: () => void }) {
  const tr = useTr();
  const { access } = useAccess();
  const people = useOrgData<People>(orgId, `/content/assets/${assetId}/people`);
  const members = useOrgData<{ results: Member[] }>(orgId, "/members?page_size=100");
  const [pick, setPick] = useState("");
  const [outsider, setOutsider] = useState({ name: "", email: "" });
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const manager = has(access, "consent.manage");
  const tagged = people.data?.tagged ?? [];

  async function save(next: { user_id?: string; name?: string; email?: string }[], ok: string) {
    setMessage(null);
    try {
      const value = await api.put<People>(`/orgs/${orgId}/content/assets/${assetId}/people`, { people: next });
      people.setData(value);
      setMessage({ kind: "ok", text: ok });
      onChange?.();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  const current = tagged.map((p) => (p.user_id ? { user_id: p.user_id } : { name: p.name, email: p.email ?? "" }));

  async function consentFor(userId: string) {
    setMessage(null);
    try {
      await api.post(`/orgs/${orgId}/content/consents`, { scope: "public_social", person_user: userId });
      people.reload();
      setMessage({ kind: "ok", text: tr("Consent recorded for public social posts.") });
      onChange?.();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  return (
    <div className="mt-3 rounded-lg p-3 ring-1 ring-inset ring-[color:var(--fb-v2-border)]">
      <p className="mb-2 text-sm font-medium">{tr("People in this recording")}</p>
      {people.data?.face_count != null && people.data.face_count > tagged.length ? (
        <Notice kind="error">
          {tr("{n} faces were detected but only {tagged} people are tagged. Tag everyone before publishing.", {
            n: people.data.face_count,
            tagged: tagged.length,
          })}
        </Notice>
      ) : null}
      {tagged.length ? (
        <ul className="mb-3 space-y-1 text-sm">
          {tagged.map((p) => (
            <li key={p.id} className="flex flex-wrap items-center justify-between gap-2">
              <span>
                {p.name}
                {p.email ? <span className="text-[color:var(--fb-v2-text-muted)]"> · {p.email}</span> : null}
              </span>
              <span className="flex items-center gap-2">
                {p.consented ? <Badge tone="good">{tr("Consented")}</Badge> : <Badge tone="bad">{tr("No consent")}</Badge>}
                {!p.consented && p.user_id && (manager || p.user_id === access?.user_id) ? (
                  <Button variant="outline" className="px-2 py-1 text-xs" onClick={() => consentFor(p.user_id as string)}>
                    {p.user_id === access?.user_id ? tr("I consent") : tr("Record consent")}
                  </Button>
                ) : null}
                {people.data?.can_remove ? (
                  <Button
                    variant="ghost"
                    className="px-2 py-1 text-xs"
                    onClick={() => save(current.filter((_, i) => tagged[i].id !== p.id), tr("Tag removed."))}
                  >
                    {tr("Remove")}
                  </Button>
                ) : null}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mb-3 text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Nobody is tagged yet. Tag everyone who appears or speaks.")}</p>
      )}
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (pick) save([...current, { user_id: pick }], tr("Tagged."));
          setPick("");
        }}
      >
        <label className="min-w-40 flex-1 text-sm">
          <span className="mb-1 block">{tr("Tag a member")}</span>
          <select className="v2-input" value={pick} onChange={(e) => setPick(e.target.value)}>
            <option value="">{tr("Choose a person")}</option>
            {rowsOf<Member>(members.data).map((m) => (
              <option key={m.id} value={m.id}>
                {m.username || m.id.slice(0, 8)}
              </option>
            ))}
          </select>
        </label>
        <Button type="submit" variant="outline" disabled={!pick}>
          {tr("Tag")}
        </Button>
      </form>
      <form
        className="mt-2 flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (outsider.name || outsider.email) save([...current, outsider], tr("Tagged."));
          setOutsider({ name: "", email: "" });
        }}
      >
        <label className="min-w-32 flex-1 text-sm">
          <span className="mb-1 block">{tr("Someone outside the org")}</span>
          <input className="v2-input" value={outsider.name} onChange={(e) => setOutsider({ ...outsider, name: e.target.value })} placeholder={tr("Name")} />
        </label>
        <label className="min-w-32 flex-1 text-sm">
          <span className="mb-1 block">{tr("Email")}</span>
          <input
            className="v2-input"
            type="email"
            value={outsider.email}
            onChange={(e) => setOutsider({ ...outsider, email: e.target.value })}
            placeholder="name@example.com"
          />
        </label>
        <Button type="submit" variant="outline" disabled={!outsider.name && !outsider.email}>
          {tr("Tag")}
        </Button>
      </form>
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
    </div>
  );
}
