"use client";

import { useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Field, Notice, Section } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, errorText } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

import { parseTopics, type CustomerSettings } from "./logic";

type Form = { auto_reply: boolean; escalation_room: string; topics: string; buddy_name: string; greeting: string; knowledge: string[] };

function formFrom(data: CustomerSettings): Form {
  return {
    auto_reply: data.auto_reply,
    escalation_room: data.escalation_room ?? "",
    topics: data.blocked_topics.join("\n"),
    buddy_name: data.buddy_name,
    greeting: data.greeting,
    knowledge: data.knowledge.map((k) => k.id),
  };
}

/** Auto reply, hand-off room, blocked topics and the documents the customer buddy may read. */
export function CustomerSettingsPanel({ orgId }: { orgId: string }) {
  const tr = useTr();
  const { data, state, error, setData } = useOrgData<CustomerSettings>(orgId, "/channels/customer-settings");
  const [edits, setDraft] = useState<Form | null>(null);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [filter, setFilter] = useState("");
  // Unsaved edits, or the saved settings when nothing was changed yet.
  const draft = edits ?? (data ? formFrom(data) : null);

  if (state === "off" || state === "no-access") return null;
  if (state === "error") return <Notice kind="error">{error || tr("Something went wrong")}</Notice>;
  if (!data || !draft) return null;

  const docs = data.documents.filter((d) => !filter || `${d.title} ${d.room}`.toLowerCase().includes(filter.toLowerCase()));
  const toggle = (id: string) =>
    setDraft({ ...draft, knowledge: draft.knowledge.includes(id) ? draft.knowledge.filter((k) => k !== id) : [...draft.knowledge, id] });

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!draft) return;
    setMessage(null);
    try {
      const next = await api.put<CustomerSettings>(`/orgs/${orgId}/channels/customer-settings`, {
        auto_reply: draft.auto_reply,
        escalation_room: draft.escalation_room || null,
        blocked_topics: parseTopics(draft.topics),
        buddy_name: draft.buddy_name,
        greeting: draft.greeting,
        knowledge: draft.knowledge,
      });
      setData(next);
      setDraft(null);
      setMessage({ kind: "ok", text: tr("Saved.") });
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  return (
    <Section title={tr("Customer buddy")}>
      <form className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4" onSubmit={save}>
        <label className="mb-1 flex items-center gap-2 text-sm font-medium">
          <input type="checkbox" checked={draft.auto_reply} onChange={(e) => setDraft({ ...draft, auto_reply: e.target.checked })} />
          {tr("Auto reply: the buddy sends its answers to customers without waiting")}
        </label>
        <p className="mb-4 text-sm text-[color:var(--fb-v2-text-muted)]">
          {draft.auto_reply
            ? tr("Answers go out right away. They still come only from the documents below.")
            : tr("Off: every answer waits as a draft until someone with permission approves it in Customers.")}
        </p>
        <div className="grid gap-x-4 md:grid-cols-2">
          <Field label={tr("Name customers see")}>
            <input className="v2-input w-full" maxLength={60} value={draft.buddy_name} onChange={(e) => setDraft({ ...draft, buddy_name: e.target.value })} />
          </Field>
          <Field label={tr("Room for hand-offs")} hint={tr("When the buddy hands a customer to a person, it posts here and notifies the room.")}>
            <select className="v2-input w-full" value={draft.escalation_room} onChange={(e) => setDraft({ ...draft, escalation_room: e.target.value })}>
              <option value="">{tr("No room")}</option>
              {data.rooms.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <Field label={tr("Greeting on the website chat")}>
          <input className="v2-input w-full" maxLength={300} value={draft.greeting} onChange={(e) => setDraft({ ...draft, greeting: e.target.value })} />
        </Field>
        <Field label={tr("Blocked topics")} hint={tr("One per line. A message that mentions one goes straight to a person.")}>
          <textarea className="v2-input min-h-20 w-full" value={draft.topics} onChange={(e) => setDraft({ ...draft, topics: e.target.value })} />
        </Field>
        <fieldset className="mb-4">
          <legend className="mb-1 text-sm font-medium">{tr("Public knowledge for customers")}</legend>
          <p className="mb-2 text-sm text-[color:var(--fb-v2-text-muted)]">
            {tr("The customer buddy reads only the documents you tick here. It never sees rooms, messages or other documents.")}
          </p>
          <input className="v2-input mb-2 w-full" placeholder={tr("Find a document")} aria-label={tr("Find a document")} value={filter} onChange={(e) => setFilter(e.target.value)} />
          <ul className="max-h-64 space-y-1 overflow-y-auto">
            {docs.map((d) => (
              <li key={d.id}>
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={draft.knowledge.includes(d.id)} onChange={() => toggle(d.id)} />
                  <span>{d.title}</span>
                  <span className="text-xs text-[color:var(--fb-v2-text-muted)]">{d.room}</span>
                </label>
              </li>
            ))}
            {docs.length === 0 ? <li className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("No documents you can open match.")}</li> : null}
          </ul>
          <p className="mt-2 text-xs text-[color:var(--fb-v2-text-muted)]">
            {tr("{n} documents are public for customers.", { n: draft.knowledge.length + data.hidden_knowledge })}
            {data.hidden_knowledge ? ` ${tr("{n} of them are in rooms you can't open; they stay as they are.", { n: data.hidden_knowledge })}` : ""}
          </p>
        </fieldset>
        {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
        <Button type="submit">{tr("Save")}</Button>
      </form>
    </Section>
  );
}
