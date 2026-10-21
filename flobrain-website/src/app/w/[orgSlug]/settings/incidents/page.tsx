"use client";

import Link from "next/link";
import { useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Badge, Field, Notice, PageHeader, Section, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { flag, has } from "@/lib/v2/access";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText, rowsOf } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

type Update = { at: string; status: string; message: string };
type Incident = {
  id: string;
  title: string;
  severity: "minor" | "major" | "critical";
  status: "investigating" | "identified" | "monitoring" | "resolved";
  components: string[];
  impact: string;
  mitigation: string;
  user_action: string;
  next_update_at: string | null;
  updates: Update[];
  created_at: string;
  resolved_at: string | null;
  is_public: boolean;
  org: string | null;
};

const COMPONENTS = ["API", "Web app", "Realtime", "AI", "Content Studio", "Webhooks"];
const SEVERITY: Record<string, string> = { minor: "Minor", major: "Major", critical: "Critical" };
const STATUS: Record<string, string> = { investigating: "Investigating", identified: "Identified", monitoring: "Monitoring", resolved: "Resolved" };
const EMPTY = { title: "", severity: "minor", components: [] as string[], impact: "", user_action: "", message: "", is_public: true };

/** One incident: what happened, its timeline, and a form to post the next update or resolve it. */
function IncidentCard({ incident, base, onSaved, editable }: { incident: Incident; base: string; onSaved: () => void; editable: boolean }) {
  const tr = useTr();
  const [message, setMessage] = useState("");
  const [status, setStatus] = useState(incident.status);
  const [mitigation, setMitigation] = useState(incident.mitigation);
  const [error, setError] = useState("");

  async function save(body: Record<string, unknown>) {
    setError("");
    try {
      await api.patch(`${base}/${incident.id}`, body);
      setMessage("");
      onSaved();
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <article className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="font-semibold">{incident.title}</h3>
        <Badge tone={incident.status === "resolved" ? "good" : "waiting"}>{tr(STATUS[incident.status] ?? incident.status)}</Badge>
        <Badge tone={incident.severity === "critical" ? "bad" : "neutral"}>{tr(SEVERITY[incident.severity] ?? incident.severity)}</Badge>
        {incident.org === null ? <Badge tone="accent">{incident.is_public ? tr("On the public status page") : tr("Platform, not public")}</Badge> : null}
      </div>
      <p className="mt-1 text-sm text-[color:var(--fb-v2-text-muted)]">
        {incident.components.join(", ")} {tr("Opened {date}.", { date: when(incident.created_at) })}
        {incident.resolved_at ? ` ${tr("Resolved {date}.", { date: when(incident.resolved_at) })}` : ""}
      </p>
      {incident.impact ? <p className="mt-2 text-sm">{incident.impact}</p> : null}
      {incident.user_action ? <p className="mt-1 text-sm">{tr("What to do: {text}", { text: incident.user_action })}</p> : null}
      {incident.mitigation ? <p className="mt-1 text-sm">{tr("What we did: {text}", { text: incident.mitigation })}</p> : null}
      <ol className="mt-3 space-y-1 border-s border-[color:var(--fb-v2-border)] ps-3 text-sm">
        {[...incident.updates].reverse().map((u, i) => (
          <li key={`${u.at}-${i}`}>
            <span className="font-medium">{tr(STATUS[u.status] ?? u.status)}</span> <span className="text-[color:var(--fb-v2-text-muted)]">{when(u.at)}</span>
            <p>{u.message}</p>
          </li>
        ))}
      </ol>
      {editable && incident.status !== "resolved" ? (
        <form
          className="mt-3 grid gap-x-4 sm:grid-cols-3"
          onSubmit={(e) => {
            e.preventDefault();
            save({ status, message, mitigation });
          }}
        >
          <Field label={tr("New status")}>
            <select className="v2-input" value={status} onChange={(e) => setStatus(e.target.value as Incident["status"])}>
              {Object.entries(STATUS).map(([key, label]) => (
                <option key={key} value={key}>
                  {tr(label)}
                </option>
              ))}
            </select>
          </Field>
          <div className="sm:col-span-2">
            <Field label={tr("Update")} hint={tr("What changed, in a sentence people can act on.")}>
              <input className="v2-input" value={message} onChange={(e) => setMessage(e.target.value)} />
            </Field>
          </div>
          <div className="sm:col-span-3">
            <Field label={tr("What we did")}>
              <input className="v2-input" value={mitigation} onChange={(e) => setMitigation(e.target.value)} />
            </Field>
          </div>
          <div className="flex gap-2 sm:col-span-3">
            <Button type="submit" variant="outline">
              {tr("Post update")}
            </Button>
            <Button type="button" onClick={() => save({ status: "resolved", message: message || undefined, mitigation })}>
              {tr("Resolve")}
            </Button>
          </div>
          {error ? <Notice kind="error">{error}</Notice> : null}
        </form>
      ) : null}
    </article>
  );
}

function IncidentList({ title, path, base, platform, editableOrg }: { title: string; path: string; base: string; platform: boolean; editableOrg?: boolean }) {
  const tr = useTr();
  const { orgId } = useAccess();
  const list = useOrgData<Incident[]>(orgId, path, { orgScoped: !platform, list: true });
  const [form, setForm] = useState(EMPTY);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  async function open() {
    setMessage(null);
    const body: Record<string, unknown> = { title: form.title, severity: form.severity, components: form.components, impact: form.impact, user_action: form.user_action, message: form.message };
    if (platform) body.is_public = form.is_public;
    try {
      await api.post(base, body);
      setForm(EMPTY);
      setMessage({ kind: "ok", text: tr("Incident opened.") });
      list.reload();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  const rows = rowsOf<Incident>(list.data).filter((i) => (platform ? true : i.org !== null));
  return (
    <Section title={title}>
      <form
        className="mb-4 rounded-xl bg-[color:var(--fb-v2-surface)] p-4"
        onSubmit={(e) => {
          e.preventDefault();
          open();
        }}
      >
        <div className="grid gap-x-4 sm:grid-cols-3">
          <div className="sm:col-span-2">
            <Field label={tr("What is wrong")}>
              <input className="v2-input" required value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
            </Field>
          </div>
          <Field label={tr("Severity")}>
            <select className="v2-input" value={form.severity} onChange={(e) => setForm({ ...form, severity: e.target.value })}>
              {Object.entries(SEVERITY).map(([key, label]) => (
                <option key={key} value={key}>
                  {tr(label)}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <fieldset className="mb-4 text-sm">
          <legend className="mb-1 font-medium">{tr("Affected")}</legend>
          {COMPONENTS.map((c) => (
            <label key={c} className="me-4 inline-flex items-center gap-2">
              <input
                type="checkbox"
                checked={form.components.includes(c)}
                onChange={(e) => setForm({ ...form, components: e.target.checked ? [...form.components, c] : form.components.filter((x) => x !== c) })}
              />
              {c}
            </label>
          ))}
        </fieldset>
        <Field label={tr("Impact")} hint={tr("Who is affected and how.")}>
          <input className="v2-input" value={form.impact} onChange={(e) => setForm({ ...form, impact: e.target.value })} />
        </Field>
        <Field label={tr("What people should do")}>
          <input className="v2-input" value={form.user_action} onChange={(e) => setForm({ ...form, user_action: e.target.value })} />
        </Field>
        {platform ? (
          <label className="mb-4 flex items-center gap-2 text-sm">
            <input type="checkbox" checked={form.is_public} onChange={(e) => setForm({ ...form, is_public: e.target.checked })} />
            {tr("Show on the public status page and email subscribers")}
          </label>
        ) : null}
        <Button type="submit">{tr("Open incident")}</Button>
      </form>
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      <ScreenBody state={list.state} error={list.error} emptyLabel={tr("No incidents.")} onRetry={list.reload}>
        {rows.length === 0 && list.state === "ready" ? <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("No incidents.")}</p> : null}
        <div className="space-y-3">
          {rows.map((i) => (
            <IncidentCard key={`${i.id}-${i.updates.length}`} incident={i} base={base} onSaved={list.reload} editable={platform || (editableOrg ?? false)} />
          ))}
        </div>
      </ScreenBody>
    </Section>
  );
}

export default function IncidentsPage() {
  const tr = useTr();
  const { orgId, access } = useAccess();
  const canOrg = has(access, "incidents.manage") && flag(access, "status_page");
  return (
    <div className="max-w-4xl">
      <PageHeader
        title={tr("Incidents")}
        intro={tr("Tell people what is broken, what to do, and when you will update them.")}
        action={
          <Link className="text-sm underline" href="/status">
            {tr("Open the status page")}
          </Link>
        }
      />
      {canOrg && orgId ? <IncidentList title={tr("This organization's incidents (private to the org)")} path="/incidents" base={`/orgs/${orgId}/incidents`} platform={false} editableOrg /> : null}
      {access?.is_platform_admin ? <IncidentList title={tr("Platform incidents")} path="/platform/incidents" base="/platform/incidents" platform /> : null}
      {!canOrg && !access?.is_platform_admin ? <Notice>{tr("You don't have permission to manage incidents.")}</Notice> : null}
    </div>
  );
}
