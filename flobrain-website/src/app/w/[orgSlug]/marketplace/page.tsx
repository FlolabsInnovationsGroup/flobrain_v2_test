"use client";

import { useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Badge, Notice, PageHeader, Section } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { has } from "@/lib/v2/access";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText, rowsOf } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

type Copy = { install: string; id: string; version: number };

type Listing = {
  id: string;
  kind: "buddy" | "content_template";
  lineage: string;
  version: number;
  changelog: string;
  title: string;
  description: string;
  status: "pending" | "approved" | "rejected" | "withdrawn" | "superseded";
  installs: number;
  submitted_by: string | null;
  decision_note: string;
  snapshot: { system_prompt?: string; allowed_tools?: string[] };
  my_copies?: Copy[];
  update_available?: boolean;
};

type ActResult = { dropped_tools?: string[]; version?: number; share_reopened?: boolean } | undefined;

export default function MarketplacePage() {
  const { orgId, access } = useAccess();
  const tr = useTr();
  const { data, state, error, reload } = useOrgData<Listing[]>(orgId, "/marketplace", { list: true });
  const { data: buddies } = useOrgData<{ id: string; name: string; mine: boolean; builtin: boolean }[]>(orgId, "/buddies");
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [offer, setOffer] = useState("");
  const [changes, setChanges] = useState<Record<string, string>>({});
  const rows = rowsOf<Listing>(data);
  const manager = has(access, "marketplace.manage");
  const myBuddies = rowsOf<{ id: string; name: string; mine: boolean; builtin: boolean }>(buddies).filter((b) => b.mine && !b.builtin);

  async function act(fn: () => Promise<unknown>, ok: string | ((result: ActResult) => string)) {
    setMessage(null);
    try {
      const result = (await fn()) as ActResult;
      const dropped = result?.dropped_tools?.length ? ` ${tr("Left out actions you can't use: {tools}.", { tools: result.dropped_tools.join(", ") })}` : "";
      setMessage({ kind: "ok", text: (typeof ok === "string" ? ok : ok(result)) + dropped });
      reload();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  const card = (l: Listing) => {
    const copies = l.my_copies ?? [];
    const older = copies.filter((c) => c.version < l.version);
    const owner = l.submitted_by === access?.user_id;
    const pendingVersion = rows.find((r) => r.lineage === l.lineage && r.status === "pending" && r.id !== l.id);
    return (
      <li key={l.id} className="flex flex-col gap-2 rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
        <div className="flex items-start justify-between gap-2">
          <div>
            <p className="font-semibold">{l.title}</p>
            <p className="text-xs text-[color:var(--fb-v2-text-muted)]">
              {tr(l.kind === "buddy" ? "Buddy" : "Video template")}. {tr("Version {n}.", { n: l.version })} {tr("Installed {n} times.", { n: l.installs })}
            </p>
          </div>
          <Badge tone={l.status === "pending" ? "waiting" : l.status === "approved" ? "good" : "neutral"}>
            {tr({ pending: "Waiting for approval", approved: "Available", rejected: "Rejected", withdrawn: "Withdrawn", superseded: "Replaced by a newer version" }[l.status])}
          </Badge>
        </div>
        <p className="text-sm">{l.description}</p>
        {l.version > 1 && l.changelog ? <p className="text-sm">{tr("What's new: {changes}", { changes: l.changelog })}</p> : null}
        {l.snapshot.system_prompt ? (
          <details className="text-sm">
            <summary className="cursor-pointer text-[color:var(--fb-v2-text-muted)]">{tr("What it is told to do")}</summary>
            <p className="mt-1 whitespace-pre-wrap">{l.snapshot.system_prompt}</p>
          </details>
        ) : null}
        {l.decision_note ? <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Note: {note}", { note: l.decision_note })}</p> : null}
        {l.update_available
          ? older.map((c) => (
              <div key={c.install} className="flex flex-col gap-2 rounded-lg border border-[color:var(--fb-v2-border)] p-3">
                <p className="text-sm font-medium">{tr("A newer version is available. Your copy is version {v}.", { v: c.version })}</p>
                <p className="text-xs text-[color:var(--fb-v2-text-muted)]">
                  {l.kind === "buddy"
                    ? tr("Updating replaces your copy's name, description, instructions, suggested prompts, actions and model with this version, so changes you made to those are lost. The rooms you picked for it to search and who you shared it with stay.")
                    : tr("Updating works like installing it again: your copy of the template is replaced with this version, and changes you made to it are lost.")}
                </p>
                <div>
                  <Button
                    variant="waiting"
                    onClick={() =>
                      act(
                        () => api.post(`/orgs/${orgId}/marketplace/installs/${c.install}/update`),
                        (r) => tr("Updated to version {n}.", { n: r?.version ?? l.version }) + (r?.share_reopened ? ` ${tr("It was shared, so it waits for approval again.")}` : ""),
                      )
                    }
                  >
                    {tr("Update my copy")}
                  </Button>
                </div>
              </div>
            ))
          : copies.length && l.status === "approved" ? (
              <p className="text-xs text-[color:var(--fb-v2-text-muted)]">{tr("Your copy is up to date.")}</p>
            ) : null}
        {l.status === "approved" && owner && pendingVersion ? (
          <p className="text-xs text-[color:var(--fb-v2-text-muted)]">{tr("Version {n} is waiting for approval.", { n: pendingVersion.version })}</p>
        ) : null}
        {l.status === "approved" && owner && !pendingVersion && has(access, "marketplace.submit") ? (
          <details className="text-sm">
            <summary className="cursor-pointer text-[color:var(--fb-v2-text-muted)]">{tr("Publish a new version")}</summary>
            <form
              className="mt-2 flex flex-col gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                act(() => api.post(`/orgs/${orgId}/marketplace/${l.id}/versions`, { changelog: changes[l.id] ?? "" }), tr("New version sent for approval."));
              }}
            >
              <p className="text-xs text-[color:var(--fb-v2-text-muted)]">
                {tr("Takes a fresh copy of what you made, as it is now. An admin approves it before anyone can update to it.")}
              </p>
              <label>
                <span className="mb-1 block font-medium">{tr("What changed?")}</span>
                <input
                  className="v2-input w-full"
                  maxLength={500}
                  required
                  value={changes[l.id] ?? ""}
                  onChange={(e) => setChanges((all) => ({ ...all, [l.id]: e.target.value }))}
                />
              </label>
              <div>
                <Button type="submit" variant="outline">
                  {tr("Send for approval")}
                </Button>
              </div>
            </form>
          </details>
        ) : null}
        <div className="mt-auto flex flex-wrap gap-2 pt-2">
          {l.status === "approved" ? (
            <Button onClick={() => act(() => api.post(`/orgs/${orgId}/marketplace/${l.id}/install`), tr("Installed. Your own copy is in Buddies."))}>{tr("Install")}</Button>
          ) : null}
          {l.status === "pending" && manager ? (
            <>
              <Button variant="waiting" onClick={() => act(() => api.post(`/orgs/${orgId}/marketplace/${l.id}/approve`), tr("Approved. Everyone can install it now."))}>
                {tr("Approve")}
              </Button>
              <Button variant="outline" onClick={() => act(() => api.post(`/orgs/${orgId}/marketplace/${l.id}/reject`, { note: "Not ready yet" }), tr("Rejected."))}>
                {tr("Reject")}
              </Button>
            </>
          ) : null}
          {(l.status === "pending" || l.status === "approved") && (manager || l.submitted_by === access?.user_id) ? (
            <Button variant="ghost" onClick={() => act(() => api.post(`/orgs/${orgId}/marketplace/${l.id}/withdraw`), tr("Withdrawn."))}>
              {tr("Withdraw")}
            </Button>
          ) : null}
        </div>
      </li>
    );
  };

  return (
    <div className="max-w-6xl">
      <PageHeader
        title={tr("Marketplace")}
        intro={tr("Buddies and video templates your colleagues made. An admin approves each one first; installing gives you your own copy, limited to what you're allowed to do.")}
      />
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      {has(access, "marketplace.submit") && myBuddies.length ? (
        <form
          className="mb-6 flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            act(() => api.post(`/orgs/${orgId}/marketplace`, { kind: "buddy", source: offer || myBuddies[0].id }), tr("Sent for approval."));
          }}
        >
          <label className="text-sm">
            <span className="mb-1 block font-medium">{tr("Offer one of your buddies")}</span>
            <select className="v2-input w-64" value={offer} onChange={(e) => setOffer(e.target.value)}>
              {myBuddies.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
            </select>
          </label>
          <Button type="submit" variant="outline">
            {tr("Offer")}
          </Button>
        </form>
      ) : null}
      <ScreenBody state={state} error={error} emptyLabel={tr("Nothing here yet. Offer a buddy you made.")} onRetry={reload}>
        {rows.some((l) => l.status === "pending") ? (
          <Section title={tr(manager ? "Waiting for your approval" : "Waiting for approval")}>
            <ul className="grid gap-3 md:grid-cols-2">{rows.filter((l) => l.status === "pending").map(card)}</ul>
          </Section>
        ) : null}
        <Section title={tr("Available")}>
          <ul className="grid gap-3 md:grid-cols-2">{rows.filter((l) => l.status === "approved").map(card)}</ul>
          {rows.every((l) => l.status !== "approved") ? <Notice>{tr("Nothing approved yet.")}</Notice> : null}
        </Section>
      </ScreenBody>
    </div>
  );
}
