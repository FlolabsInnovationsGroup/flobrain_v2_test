"use client";

import { Badge, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";

export type PublicIncident = {
  id?: string;
  title: string;
  severity: string;
  status: string;
  components: string[];
  impact: string;
  mitigation?: string;
  user_action: string;
  next_update_at?: string | null;
  updates: { at: string; status: string; message: string }[];
  created_at: string;
  resolved_at: string | null;
};
export type StatusData = { generated_at: string; overall?: string; components: { name: string; status: string }[]; incidents: PublicIncident[] };

const STATE: Record<string, { label: string; tone: "good" | "waiting" | "bad" }> = {
  operational: { label: "Operational", tone: "good" },
  degraded: { label: "Degraded", tone: "waiting" },
  partial_outage: { label: "Partial outage", tone: "bad" },
  major_outage: { label: "Major outage", tone: "bad" },
};
const PHASE: Record<string, string> = { investigating: "Investigating", identified: "Identified", monitoring: "Monitoring", resolved: "Resolved" };
const HEADLINE: Record<string, string> = {
  operational: "All systems are working.",
  degraded: "Some parts of FloBrain are slow.",
  partial_outage: "Part of FloBrain is down.",
  major_outage: "FloBrain has a major outage.",
};

/** The public status projection: overall state, components, open incidents and history. */
export function StatusView({ data }: { data: StatusData }) {
  const tr = useTr();
  const worst = data.overall ?? (data.components.find((c) => c.status !== "operational")?.status || "operational");
  const open = data.incidents.filter((i) => i.status !== "resolved");
  const past = data.incidents.filter((i) => i.status === "resolved");
  const tone = STATE[worst]?.tone ?? "waiting";
  return (
    <>
      <div
        className="rounded-2xl p-5 text-lg font-semibold ring-1 ring-inset"
        style={{ boxShadow: "none", color: tone === "good" ? "var(--fb-v2-success)" : tone === "bad" ? "var(--fb-v2-error)" : "var(--fb-v2-waiting)" }}
        role="status"
      >
        {tr(HEADLINE[worst] ?? "Some parts of FloBrain are slow.")}
      </div>
      <ul className="mt-6 divide-y divide-[color:var(--fb-v2-border)] rounded-xl bg-[color:var(--fb-v2-surface)]">
        {data.components.map((c) => (
          <li key={c.name} className="flex items-center justify-between px-4 py-3">
            <span>{tr(c.name)}</span>
            <Badge tone={STATE[c.status]?.tone ?? "waiting"}>{tr(STATE[c.status]?.label ?? c.status)}</Badge>
          </li>
        ))}
      </ul>
      {open.length ? (
        <section className="mt-8">
          <h2 className="mb-3 text-lg font-semibold">{tr("Happening now")}</h2>
          <div className="space-y-3">
            {open.map((i) => (
              <IncidentBlock key={i.id ?? i.created_at} incident={i} />
            ))}
          </div>
        </section>
      ) : null}
      <section className="mt-8">
        <h2 className="mb-3 text-lg font-semibold">{tr("Past incidents")}</h2>
        {past.length ? (
          <div className="space-y-3">
            {past.map((i) => (
              <IncidentBlock key={i.id ?? i.created_at} incident={i} />
            ))}
          </div>
        ) : (
          <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("No incidents reported.")}</p>
        )}
      </section>
      <p className="mt-6 text-xs text-[color:var(--fb-v2-text-muted)]">{tr("Updated {date}", { date: when(data.generated_at) })}</p>
    </>
  );
}

function IncidentBlock({ incident }: { incident: PublicIncident }) {
  const tr = useTr();
  return (
    <article className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="font-semibold">{incident.title}</h3>
        <Badge tone={incident.status === "resolved" ? "good" : "waiting"}>{tr(PHASE[incident.status] ?? incident.status)}</Badge>
      </div>
      <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
        {incident.components.map((c) => tr(c)).join(", ")}. {when(incident.created_at)}
        {incident.resolved_at ? ` ${tr("to")} ${when(incident.resolved_at)}` : ""}
      </p>
      {incident.impact ? <p className="mt-2 text-sm">{incident.impact}</p> : null}
      {incident.user_action ? <p className="mt-1 text-sm">{tr("What to do: {text}", { text: incident.user_action })}</p> : null}
      {incident.next_update_at && incident.status !== "resolved" ? <p className="mt-1 text-sm">{tr("Next update by {date}", { date: when(incident.next_update_at) })}</p> : null}
      <ol className="mt-3 space-y-1 border-s border-[color:var(--fb-v2-border)] ps-3 text-sm">
        {[...incident.updates].reverse().map((u, n) => (
          <li key={`${u.at}-${n}`}>
            <span className="font-medium">{tr(PHASE[u.status] ?? u.status)}</span> <span className="text-[color:var(--fb-v2-text-muted)]">{when(u.at)}</span>
            <p>{u.message}</p>
          </li>
        ))}
      </ol>
    </article>
  );
}
