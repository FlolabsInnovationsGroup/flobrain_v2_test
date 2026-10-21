"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Badge, Notice, PageHeader, Row, Rows, Section } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, rowsOf } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

type Counts = {
  tasks_done: number;
  seconds: number;
  messages: number;
  meetings: number;
  ai_requests: number;
};
type Mine = {
  days: number;
  current: Counts;
  previous: Counts;
  open_tasks: number;
  overdue_tasks: number;
  hours_by_day: { day: string; seconds: number }[];
  hours_by_category: { category: string; seconds: number }[];
  busiest_weekday: string | null;
  personal_only: boolean;
};
type TeamRow = {
  user_id: string;
  name: string;
  tasks_done: number;
  seconds: number;
  meetings: number;
};
type TeamInsights = {
  team: { id: string; name: string };
  members: TeamRow[];
  totals: Omit<TeamRow, "user_id" | "name">;
  private_count: number;
};
type Team = { id: string; name: string };

const PERIODS = [7, 30, 90];
const CATEGORY: Record<string, string> = {
  projects: "Projects",
  onboarding: "Onboarding",
  masterclass: "Masterclass",
};

function hours(seconds: number) {
  return (seconds / 3600).toFixed(seconds >= 36000 ? 0 : 1);
}

function Change({ now, before }: { now: number; before: number }) {
  const tr = useTr();
  if (now === before)
    return (
      <span className="text-xs text-[color:var(--fb-v2-text-muted)]">{tr("same as before")}</span>
    );
  const up = now > before;
  return (
    <span className="text-xs text-[color:var(--fb-v2-text-muted)]">
      {up ? tr("up from {n}", { n: before }) : tr("down from {n}", { n: before })}
    </span>
  );
}

/** Your own work in numbers. Only you see this page's first part; leads also see their teams. */
export default function InsightsPage() {
  const { orgSlug } = useParams<{ orgSlug: string }>();
  const { orgId, access } = useAccess();
  const tr = useTr();
  const [days, setDays] = useState(30);
  const mine = useOrgData<Mine>(orgId, `/me/insights?days=${days}`);
  const teams = useOrgData<Team[]>(orgId, access?.leads_teams.length ? "/teams" : null, {
    list: true,
  });
  const myTeams = rowsOf<Team>(teams.data).filter((t) => access?.leads_teams.includes(t.id));
  const [teamId, setTeamId] = useState("");
  const [team, setTeam] = useState<TeamInsights | null>(null);
  const [teamError, setTeamError] = useState("");
  const chosen = teamId || myTeams[0]?.id || "";

  useEffect(() => {
    if (!orgId || !chosen) return;
    api
      .get<TeamInsights>(`/orgs/${orgId}/teams/${chosen}/insights?days=${days}`)
      .then((d) => {
        setTeam(d);
        setTeamError("");
      })
      .catch(() => setTeamError(tr("Could not load the team's insights.")));
  }, [orgId, chosen, days, tr]);

  const d = mine.data;
  const peak = Math.max(1, ...(d?.hours_by_day ?? []).map((r) => r.seconds));
  const tiles: { label: string; key: keyof Counts; format?: (n: number) => string }[] = [
    { label: "Tasks done", key: "tasks_done" },
    { label: "Hours logged", key: "seconds", format: hours },
    { label: "Meetings you spoke in", key: "meetings" },
    { label: "Messages", key: "messages" },
    { label: "AI requests", key: "ai_requests" },
  ];

  return (
    <div className="max-w-4xl">
      <PageHeader
        title={tr("Insights")}
        intro={tr("Your own work in numbers. Only you see your insights.")}
        action={
          <div role="group" aria-label={tr("Period")} className="flex gap-1">
            {PERIODS.map((n) => (
              <button
                key={n}
                type="button"
                aria-pressed={days === n}
                onClick={() => setDays(n)}
                className={`rounded-lg px-3 py-1 text-sm ${days === n ? "bg-[color:var(--fb-v2-accent)] text-white" : "bg-[color:var(--fb-v2-surface)]"}`}
              >
                {tr("{n} days", { n })}
              </button>
            ))}
          </div>
        }
      />
      <ScreenBody state={mine.state} error={mine.error} onRetry={mine.reload}>
        {d ? (
          <>
            <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
              {tiles.map((t) => (
                <div key={t.key} className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
                  <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr(t.label)}</p>
                  <p className="text-2xl font-semibold tabular-nums">
                    {(t.format ?? String)(d.current[t.key])}
                  </p>
                  <Change
                    now={Number((t.format ?? String)(d.current[t.key]))}
                    before={Number((t.format ?? String)(d.previous[t.key]))}
                  />
                </div>
              ))}
            </div>
            <p className="mb-6 text-sm">
              {tr("{open} open tasks assigned to you, {overdue} overdue.", {
                open: d.open_tasks,
                overdue: d.overdue_tasks,
              })}{" "}
              <Link className="underline" href={`/w/${orgSlug}/tasks`}>
                {tr("Open tasks")}
              </Link>
            </p>

            <Section title={tr("Hours by day")}>
              {d.hours_by_day.length ? (
                <>
                  <div
                    className="flex h-32 items-end gap-[2px] rounded-xl bg-[color:var(--fb-v2-surface)] p-3"
                    aria-hidden
                  >
                    {d.hours_by_day.map((r) => (
                      <div
                        key={r.day}
                        title={`${r.day}: ${hours(r.seconds)} h`}
                        className="min-w-[6px] flex-1 rounded-t bg-[color:var(--fb-v2-accent)]"
                        style={{ height: `${Math.max(4, (r.seconds / peak) * 100)}%` }}
                      />
                    ))}
                  </div>
                  <ul className="sr-only">
                    {d.hours_by_day.map((r) => (
                      <li key={r.day}>{`${r.day}: ${hours(r.seconds)} h`}</li>
                    ))}
                  </ul>
                  {d.busiest_weekday ? (
                    <p className="mt-2 text-sm text-[color:var(--fb-v2-text-muted)]">
                      {tr("Your busiest day is usually {day}.", { day: tr(d.busiest_weekday) })}
                    </p>
                  ) : null}
                </>
              ) : (
                <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
                  {tr("No time logged in this period.")}
                </p>
              )}
            </Section>

            {d.hours_by_category.length ? (
              <Section title={tr("Where your hours went")}>
                <Rows>
                  {d.hours_by_category.map((c) => (
                    <Row key={c.category}>
                      <span>{tr(CATEGORY[c.category] ?? c.category)}</span>
                      <span className="tabular-nums">{tr("{h} h", { h: hours(c.seconds) })}</span>
                    </Row>
                  ))}
                </Rows>
              </Section>
            ) : null}

            <div className="mb-8">
              <Notice>
                {d.personal_only
                  ? tr(
                      "You keep your insights personal: your team leads don't see you in team insights."
                    )
                  : tr(
                      "Your team leads see your tasks done, hours and meetings in team insights, never your messages or AI use."
                    )}{" "}
                <Link className="underline" href={`/w/${orgSlug}/privacy`}>
                  {tr("Change this in Privacy")}
                </Link>
              </Notice>
            </div>
          </>
        ) : null}
      </ScreenBody>

      {myTeams.length ? (
        <Section
          title={tr("Your teams")}
          aside={
            myTeams.length > 1 ? (
              <select
                className="v2-input w-48"
                value={chosen}
                onChange={(e) => setTeamId(e.target.value)}
                aria-label={tr("Team")}
              >
                {myTeams.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </select>
            ) : null
          }
        >
          {teamError ? <Notice kind="error">{teamError}</Notice> : null}
          {team ? (
            <>
              <Rows>
                {team.members.map((m) => (
                  <Row key={m.user_id}>
                    <span className="font-medium">{m.name}</span>
                    <span className="text-sm tabular-nums">
                      {tr("{t} tasks, {h} h, {m} meetings", {
                        t: m.tasks_done,
                        h: hours(m.seconds),
                        m: m.meetings,
                      })}
                    </span>
                  </Row>
                ))}
              </Rows>
              <p className="mt-2 text-sm text-[color:var(--fb-v2-text-muted)]">
                {tr("Team total: {t} tasks, {h} h, {m} meetings.", {
                  t: team.totals.tasks_done,
                  h: hours(team.totals.seconds),
                  m: team.totals.meetings,
                })}{" "}
                {team.private_count ? (
                  <Badge>
                    {tr("{n} people keep their insights personal", { n: team.private_count })}
                  </Badge>
                ) : null}
              </p>
            </>
          ) : null}
        </Section>
      ) : null}
    </div>
  );
}
