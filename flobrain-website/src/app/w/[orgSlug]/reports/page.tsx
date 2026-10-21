"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Badge, Field, Notice, PageHeader, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText, rowsOf } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

type Report = {
  id: string;
  kind: string;
  period_start: string;
  period_end: string;
  content: string;
  generated_at: string;
  posted_at: string | null;
};

export default function ReportsPage() {
  const { orgId, access } = useAccess();
  const tr = useTr();
  const { data: teams } = useOrgData<{ id: string; name: string }[]>(orgId, "/teams");
  const [team, setTeam] = useState("");
  const [reports, setReports] = useState<Report[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const teamRows = rowsOf<{ id: string; name: string }>(teams).filter(
    (t) => access?.org_role === "owner" || access?.org_role === "admin" || access?.leads_teams.includes(t.id),
  );
  const current = team || teamRows[0]?.id || "";

  useEffect(() => {
    if (!orgId || !current) return;
    api
      .get(`/orgs/${orgId}/teams/${current}/reports`)
      .then((v) => setReports(rowsOf<Report>(v)))
      .catch((err) => setMessage({ kind: "error", text: errorText(err) }));
  }, [orgId, current]);

  async function generate(kind: string) {
    setBusy(true);
    setMessage(null);
    try {
      const report = await api.post<Report>(`/orgs/${orgId}/teams/${current}/reports/generate`, { kind });
      setReports((prev) => [report, ...prev]);
      setMessage({ kind: "ok", text: tr("Draft ready. Read it, then post it to the team room.") });
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    } finally {
      setBusy(false);
    }
  }

  async function post(id: string) {
    try {
      const report = await api.post<Report>(`/orgs/${orgId}/teams/${current}/reports/${id}/post`);
      setReports((prev) => prev.map((r) => (r.id === id ? report : r)));
      setMessage({ kind: "ok", text: tr("Posted to the team room.") });
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  return (
    <div className="max-w-4xl">
      <PageHeader
        title={tr("Team reports")}
        intro={tr("Drafts of the daily stand-up and weekly report, built from tasks, time and rooms. Nothing is posted until you choose to.")}
      />
      {teamRows.length === 0 ? (
        <Notice>{tr("Reports are for team leads and admins.")}</Notice>
      ) : (
        <div className="mb-6 flex flex-wrap items-end gap-3">
          <Field label={tr("Team")}>
            <select className="v2-input w-56" value={current} onChange={(e) => setTeam(e.target.value)}>
              {teamRows.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
          </Field>
          <div className="mb-4 flex gap-2">
            <Button onClick={() => generate("weekly_report")} disabled={busy}>
              {tr("Draft weekly report")}
            </Button>
            <Button variant="outline" onClick={() => generate("daily_standup")} disabled={busy}>
              {tr("Draft stand-up")}
            </Button>
          </div>
        </div>
      )}
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      <div className="space-y-4">
        {reports.map((r) => (
          <article key={r.id} className="rounded-xl bg-[color:var(--fb-v2-surface)] p-5">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <h2 className="font-semibold">
                {tr("{kind}, {start} to {end}", { kind: r.kind === "weekly_report" ? tr("Weekly report") : tr("Stand-up"), start: r.period_start, end: r.period_end })}
              </h2>
              {r.posted_at ? (
                <Badge tone="good">{tr("Posted {when}", { when: when(r.posted_at) })}</Badge>
              ) : (
                <Button variant="outline" onClick={() => post(r.id)}>
                  {tr("Post to team room")}
                </Button>
              )}
            </div>
            <p className="whitespace-pre-wrap text-sm">{r.content}</p>
          </article>
        ))}
      </div>
    </div>
  );
}
