"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import { AskFloHint, CrewTemplates } from "@/components/v2/crew/Templates";
import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Badge, Field, Notice, PageHeader, Section } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { flag, has, isLead } from "@/lib/v2/access";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText, rowsOf } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

export type BuddyRow = {
  id: string;
  slug?: string;
  name: string;
  description: string;
  icon: string;
  visibility: "private" | "team" | "org";
  share_status: string;
  builtin: boolean;
  mine: boolean;
  allowed_tools: string[];
  sources: string;
};

const TOOLS = [
  ["tasks.create", "Create tasks"],
  ["tasks.assign", "Assign tasks"],
  ["rooms.post_message", "Post in rooms"],
  ["email.draft", "Draft emails"],
  ["meetings.create", "Schedule meetings"],
] as const;

function visibilityLabel(row: BuddyRow, tr: (text: string) => string) {
  if (row.builtin) return tr("Built in");
  if (row.share_status === "pending") return tr("Waiting for approval");
  return tr({ private: "Only you", team: "Your team", org: "Everyone" }[row.visibility]);
}

export default function BuddiesPage() {
  const { orgSlug } = useParams<{ orgSlug: string }>();
  const router = useRouter();
  const { orgId, access } = useAccess();
  const tr = useTr();
  const { data, state, error, reload } = useOrgData<BuddyRow[]>(orgId, "/buddies", { list: true });
  const reviewer = has(access, "buddy.manage") || isLead(access);
  const requests = useOrgData<{ id: string }[]>(orgId, reviewer ? "/buddies/share-requests" : null, { list: true });
  const waiting = rowsOf<{ id: string }>(requests.data).length;
  const [building, setBuilding] = useState(false);
  const [form, setForm] = useState({ name: "", description: "", system_prompt: "", sources: "accessible", tools: [] as string[] });
  const [message, setMessage] = useState("");
  const rows = rowsOf<BuddyRow>(data);
  const mine = rows.filter((row) => row.mine && !row.builtin);
  const shared = rows.filter((row) => !row.mine || row.builtin);
  // Crew (W5): Flo and specialist templates, behind the flo_router flag.
  const crew = flag(access, "flo_router");
  const flo = crew ? rows.find((row) => row.slug === "flo" && row.builtin) : undefined;
  const quality = flag(access, "buddies") && (has(access, "pulse.view") || has(access, "ai.usage.view"));

  async function create(event: React.FormEvent) {
    event.preventDefault();
    setMessage("");
    try {
      const made = await api.post<BuddyRow>(`/orgs/${orgId}/buddies`, {
        name: form.name,
        description: form.description,
        system_prompt: form.system_prompt,
        allowed_sources: { mode: form.sources, source_types: ["doc", "room_message"] },
        allowed_tools: form.tools,
      });
      router.push(`/w/${orgSlug}/buddies/${made.id}`);
    } catch (err) {
      setMessage(errorText(err));
    }
  }

  const list = (items: BuddyRow[]) => (
    <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {items.map((row) => (
        <li key={row.id}>
          <Link
            href={`/w/${orgSlug}/buddies/${row.id}`}
            className="flex h-full flex-col gap-2 rounded-xl bg-[color:var(--fb-v2-surface)] p-4 ring-1 ring-inset ring-[color:var(--fb-v2-border)] hover:ring-[color:var(--fb-v2-accent)]"
          >
            <span className="flex items-center justify-between gap-2">
              <span className="font-semibold">{row.name}</span>
              <Badge tone={row.share_status === "pending" ? "waiting" : "neutral"}>{visibilityLabel(row, tr)}</Badge>
            </span>
            <span className="text-sm text-[color:var(--fb-v2-text-muted)]">{row.description || tr("No description yet.")}</span>
            {row.allowed_tools.length ? (
              <span className="mt-auto text-xs text-[color:var(--fb-v2-text-muted)]">
                {tr("Can propose: {tools}", { tools: row.allowed_tools.map((t) => { const label = TOOLS.find(([k]) => k === t)?.[1]; return label ? tr(label) : t; }).join(tr(", ")) })}
              </span>
            ) : null}
          </Link>
        </li>
      ))}
    </ul>
  );

  return (
    <div className="max-w-6xl">
      <PageHeader
        title={tr("Buddies")}
        intro={tr("Assistants with a job. Each one answers from what you can already open, and proposes actions for you to approve.")}
        action={
          <div className="flex flex-wrap gap-2">
            {crew && quality ? (
              <Button asChild variant="outline">
                <Link href={`/w/${orgSlug}/buddies/quality`}>{tr("Buddy quality")}</Link>
              </Button>
            ) : null}
            {reviewer ? (
              <Button asChild variant={waiting ? "waiting" : "outline"}>
                <Link href={`/w/${orgSlug}/buddies/requests`}>{waiting ? tr("Share requests ({n})", { n: waiting }) : tr("Share requests")}</Link>
              </Button>
            ) : null}
            {has(access, "buddy.create") ? (
              <Button onClick={() => setBuilding((v) => !v)}>{building ? tr("Close") : tr("Build a buddy")}</Button>
            ) : null}
          </div>
        }
      />
      {building ? (
        <form onSubmit={create} className="mb-8 max-w-2xl rounded-xl bg-[color:var(--fb-v2-surface)] p-5">
          <Field label={tr("Name")}>
            <input className="v2-input" required maxLength={80} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </Field>
          <Field label={tr("What it does")} hint={tr("One sentence your colleagues will read.")}>
            <input className="v2-input" maxLength={300} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </Field>
          <Field label={tr("Instructions")} hint={tr("How it should behave. It never sees rooms or documents you can't open.")}>
            <textarea className="v2-input min-h-28" maxLength={4000} value={form.system_prompt} onChange={(e) => setForm({ ...form, system_prompt: e.target.value })} />
          </Field>
          <Field label={tr("Knowledge")}>
            <select className="v2-input" value={form.sources} onChange={(e) => setForm({ ...form, sources: e.target.value })}>
              <option value="accessible">{tr("Rooms and documents I can open")}</option>
              <option value="none">{tr("No org knowledge")}</option>
            </select>
          </Field>
          <fieldset className="mb-4">
            <legend className="mb-1 text-sm font-medium">{tr("Actions it may propose")}</legend>
            {TOOLS.map(([key, label]) => (
              <label key={key} className="me-4 inline-flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={form.tools.includes(key)}
                  onChange={(e) =>
                    setForm({ ...form, tools: e.target.checked ? [...form.tools, key] : form.tools.filter((t) => t !== key) })
                  }
                />
                {tr(label)}
              </label>
            ))}
          </fieldset>
          {message ? <Notice kind="error">{message}</Notice> : null}
          <Button type="submit">{tr("Create buddy")}</Button>
        </form>
      ) : null}
      <ScreenBody state={state} error={error} emptyLabel={tr("No buddies yet. Build the first one.")} onRetry={reload}>
        {flo ? <AskFloHint orgSlug={orgSlug} floId={flo.id} /> : null}
        {mine.length ? <Section title={tr("Your buddies")}>{list(mine)}</Section> : null}
        <Section title={tr("Shared with you")}>{list(shared)}</Section>
      </ScreenBody>
      {crew ? <CrewTemplates orgId={orgId} orgSlug={orgSlug} onInstalled={reload} /> : null}
    </div>
  );
}
