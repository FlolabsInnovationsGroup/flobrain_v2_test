"use client";

import Link from "next/link";
import { useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Breakdown, type BreakdownRow } from "@/components/v2/timer/Breakdown";
import { WeekPicker } from "@/components/v2/timer/WeekPicker";
import { Badge, PageHeader, Row, Rows, Section } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { useAccess } from "@/lib/v2/AccessContext";
import { categoryLabel, formatDuration, mondayOf } from "@/lib/v2/screens/time";
import { useOrgData } from "@/lib/v2/useOrgData";

type Bucket = { id: string | null; name: string; seconds: number; private?: boolean };
type Report = {
  seconds: number;
  entries: number;
  by_category: Array<{ key: string; seconds: number }>;
  by_project: Bucket[];
  by_task: Bucket[];
  by_room: Bucket[];
};
type TeamReport = Report & {
  team_name: string;
  by_member: Array<{
    user_id: string;
    name: string;
    seconds: number;
    entries: number;
    submitted: number;
    approved: number;
    weekly_target_hours: string | null;
    capacity_seconds: number | null;
  }>;
};

function useRows(tr: (s: string) => string) {
  return {
    categories: (r: Report | null): BreakdownRow[] => (r?.by_category ?? []).map((row) => ({ key: row.key, label: tr(categoryLabel(row.key)), seconds: row.seconds })),
    buckets: (rows: Bucket[] | undefined, none: string): BreakdownRow[] =>
      (rows ?? []).map((row) => ({
        key: row.private ? "private" : (row.id ?? "none"),
        label: row.private ? tr("Private (not one you can open)") : row.id ? row.name : none,
        seconds: row.seconds,
      })),
  };
}

function ReportGrid({ report }: { report: Report | null }) {
  const tr = useTr();
  const rows = useRows(tr);
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Breakdown title={tr("By category")} rows={rows.categories(report)} />
      <Breakdown title={tr("By project")} rows={rows.buckets(report?.by_project, tr("No project"))} />
      <Breakdown title={tr("By task")} rows={rows.buckets(report?.by_task, tr("No task"))} />
      <Breakdown title={tr("By room")} rows={rows.buckets(report?.by_room, tr("No room"))} />
    </div>
  );
}

/** Your week, and for leads and admins the week of a team they can see. */
export function TimeReports({ orgSlug }: { orgSlug: string }) {
  const tr = useTr();
  const { orgId, access } = useAccess();
  const [week, setWeek] = useState(() => mondayOf(new Date()));
  const admin = access?.org_role === "owner" || access?.org_role === "admin" || !!access?.is_platform_admin;
  const teams = useOrgData<Array<{ id: string; name: string }>>(orgId, "/teams");
  const reviewable = (teams.data ?? []).filter((t) => admin || access?.leads_teams.includes(t.id));
  const [team, setTeam] = useState("");
  const teamId = team || reviewable[0]?.id || "";
  const mine = useOrgData<Report>(orgId, `/time-reports/me?week=${week}`);
  const teamReport = useOrgData<TeamReport>(orgId, teamId ? `/time-reports/team/${teamId}?week=${week}` : null);

  return (
    <div className="max-w-6xl">
      <PageHeader
        title={tr("Time reports")}
        intro={tr("Hours by category, project, task and room for one week. Durations are hours and minutes.")}
        action={
          <Link className="text-sm underline" href={`/w/${orgSlug}/time`}>
            {tr("Back to Time")}
          </Link>
        }
      />
      <div className="mb-6">
        <WeekPicker value={week} onChange={setWeek} />
      </div>

      <Section title={tr("My week")} aside={<span className="font-mono text-lg font-semibold tabular-nums">{formatDuration(mine.data?.seconds ?? 0)}</span>}>
        <ScreenBody state={mine.state} error={mine.error} onRetry={mine.reload}>
          <ReportGrid report={mine.data} />
        </ScreenBody>
      </Section>

      {reviewable.length ? (
        <Section
          title={tr("Team week")}
          aside={
            <select className="v2-input w-auto py-1" aria-label={tr("Team")} value={teamId} onChange={(e) => setTeam(e.target.value)}>
              {reviewable.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
          }
        >
          <ScreenBody state={teamReport.state} error={teamReport.error} onRetry={teamReport.reload}>
            {teamReport.data ? (
              <div className="space-y-4">
                <p className="text-sm">
                  {tr("{team} logged {time} across {n} entries.", {
                    team: teamReport.data.team_name,
                    time: formatDuration(teamReport.data.seconds),
                    n: teamReport.data.entries,
                  })}
                </p>
                <Rows>
                  {teamReport.data.by_member.map((m) => (
                    <Row key={m.user_id}>
                      <div>
                        <p className="font-medium">{m.name}</p>
                        <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
                          {m.weekly_target_hours
                            ? tr("Target {h} h. {left} left this week.", {
                                h: m.weekly_target_hours.replace(/\.00$/, ""),
                                left: formatDuration(Math.max(0, m.capacity_seconds ?? 0)),
                              })
                            : tr("No weekly target")}
                        </p>
                      </div>
                      <div className="flex items-center gap-2">
                        {m.submitted ? <Badge tone="waiting">{tr("{n} waiting", { n: m.submitted })}</Badge> : null}
                        {m.approved ? <Badge tone="good">{tr("{n} approved", { n: m.approved })}</Badge> : null}
                        <span className="w-14 text-end font-mono tabular-nums">{formatDuration(m.seconds)}</span>
                      </div>
                    </Row>
                  ))}
                </Rows>
                <ReportGrid report={teamReport.data} />
                <p className="text-xs text-[color:var(--fb-v2-text-muted)]">
                  {tr("People who keep their time details private appear in totals only.")}
                </p>
              </div>
            ) : null}
          </ScreenBody>
        </Section>
      ) : null}
    </div>
  );
}
