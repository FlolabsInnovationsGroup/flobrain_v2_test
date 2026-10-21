"use client";

import { useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Badge, Notice, PageHeader, Row, Rows, Section, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";
import { cn } from "@/lib/utils";

type Item = {
  id: string;
  kind: "bug" | "idea" | "question";
  page: string;
  text: string;
  browser: string;
  screenshot_note: string;
  status: "new" | "triaged" | "closed";
  created_at: string;
  user?: { id: string; username: string } | null;
};
type Cell = { events: number; users: number };
type Analytics = {
  days: number;
  min_users: number;
  count: number;
  active_users: number | null;
  pages: (Cell & { page: string })[];
  features: (Cell & { feature: string })[];
  by_day: (Cell & { day: string })[];
  hidden: { pages: number; features: number; days: number };
};

const KIND = { bug: "Problem", idea: "Idea", question: "Question" } as const;
const STATUS = { new: "New", triaged: "Triaged", closed: "Closed" } as const;

export default function FeedbackPage() {
  const tr = useTr();
  const { orgId, access } = useAccess();
  const admin = access?.org_role === "owner" || access?.org_role === "admin" || !!access?.is_platform_admin;
  const [tab, setTab] = useState<"inbox" | "analytics" | "mine">("inbox");
  const current = admin ? tab : "mine";

  return (
    <div className="max-w-5xl">
      <PageHeader
        title={admin ? tr("Feedback and analytics") : tr("Your reports")}
        intro={
          admin
            ? tr("What people reported with the Report a problem button, and how the main screens are used. Counts below five people are hidden.")
            : tr("Problems and ideas you sent with the Report a problem button, and where they are.")
        }
      />
      {admin ? (
        <div role="tablist" aria-label={tr("Feedback and analytics")} className="mb-4 flex gap-1">
          {(["inbox", "analytics", "mine"] as const).map((key) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={current === key}
              onClick={() => setTab(key)}
              className={cn("rounded-md px-3 py-1 text-sm", current === key ? "bg-[color:var(--fb-v2-accent)] text-white" : "hover:bg-[color:var(--fb-v2-border)]")}
            >
              {tr(key === "inbox" ? "Inbox" : key === "analytics" ? "Product analytics" : "Your reports")}
            </button>
          ))}
        </div>
      ) : null}
      {orgId && current === "inbox" ? <Inbox orgId={orgId} /> : null}
      {orgId && current === "analytics" ? <AnalyticsView orgId={orgId} /> : null}
      {orgId && current === "mine" ? <Mine orgId={orgId} /> : null}
    </div>
  );
}

function Inbox({ orgId }: { orgId: string }) {
  const tr = useTr();
  const [status, setStatus] = useState("new");
  const items = useOrgData<{ results: Item[] }>(orgId, `/admin/feedback?page_size=100${status ? `&status=${status}` : ""}`, { list: true });
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  async function move(item: Item, next: Item["status"]) {
    setMessage(null);
    try {
      await api.patch(`/orgs/${orgId}/admin/feedback/${item.id}`, { status: next });
      setMessage({ kind: "ok", text: tr("Moved to {status}.", { status: tr(STATUS[next]) }) });
      items.reload();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  return (
    <>
      <label className="mb-3 inline-block text-sm">
        <span className="me-2 font-medium">{tr("Show")}</span>
        <select className="v2-input w-auto" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="new">{tr("New")}</option>
          <option value="triaged">{tr("Triaged")}</option>
          <option value="closed">{tr("Closed")}</option>
          <option value="">{tr("All")}</option>
        </select>
      </label>
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      <ScreenBody state={items.state} error={items.error} emptyLabel={tr("Nothing here. New reports show up as people send them.")} onRetry={items.reload}>
        <Rows>
          {(items.data?.results ?? []).map((item) => (
            <Row key={item.id} className="items-start">
              <div className="min-w-0 max-w-2xl">
                <p className="mb-1 flex flex-wrap items-center gap-2 text-sm">
                  <Badge tone={item.kind === "bug" ? "bad" : "accent"}>{tr(KIND[item.kind])}</Badge>
                  <span className="text-[color:var(--fb-v2-text-muted)]">
                    {item.user?.username ?? tr("Someone who left")} · {item.page || "/"} · {when(item.created_at)}
                  </span>
                </p>
                <p className="whitespace-pre-wrap">{item.text}</p>
                {item.screenshot_note ? (
                  <p className="mt-1 text-sm text-[color:var(--fb-v2-text-muted)]">{tr("What the screen showed: {note}", { note: item.screenshot_note })}</p>
                ) : null}
                {item.browser ? <p className="text-xs text-[color:var(--fb-v2-text-muted)]">{item.browser}</p> : null}
              </div>
              <div className="flex gap-2">
                {item.status !== "triaged" ? (
                  <Button variant="outline" onClick={() => move(item, "triaged")}>
                    {tr("Mark triaged")}
                  </Button>
                ) : null}
                {item.status !== "closed" ? (
                  <Button variant="ghost" onClick={() => move(item, "closed")}>
                    {tr("Close")}
                  </Button>
                ) : (
                  <Button variant="ghost" onClick={() => move(item, "new")}>
                    {tr("Reopen")}
                  </Button>
                )}
              </div>
            </Row>
          ))}
        </Rows>
      </ScreenBody>
    </>
  );
}

function Bar({ value, max }: { value: number; max: number }) {
  return (
    <span aria-hidden className="block h-1.5 rounded-full bg-[color:var(--fb-v2-border)]">
      <span className="block h-1.5 rounded-full bg-[color:var(--fb-v2-accent)]" style={{ width: `${max ? Math.max(4, (value / max) * 100) : 0}%` }} />
    </span>
  );
}

function AnalyticsView({ orgId }: { orgId: string }) {
  const tr = useTr();
  const [days, setDays] = useState(30);
  const data = useOrgData<Analytics>(orgId, `/admin/analytics?days=${days}`);
  const a = data.data;
  const maxPage = Math.max(0, ...(a?.pages ?? []).map((p) => p.events));
  const maxDay = Math.max(0, ...(a?.by_day ?? []).map((d) => d.events));

  return (
    <>
      <label className="mb-3 inline-block text-sm">
        <span className="me-2 font-medium">{tr("Period")}</span>
        <select className="v2-input w-auto" value={days} onChange={(e) => setDays(Number(e.target.value))}>
          <option value={7}>{tr("Last 7 days")}</option>
          <option value={30}>{tr("Last 30 days")}</option>
          <option value={90}>{tr("Last 90 days")}</option>
        </select>
      </label>
      <ScreenBody state={data.state} error={data.error} onRetry={data.reload}>
        {a ? (
          <>
            <div className="mb-6 grid gap-4 sm:grid-cols-2">
              <div className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
                <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Events recorded")}</p>
                <p className="text-3xl font-semibold tabular-nums">{a.count.toLocaleString()}</p>
              </div>
              <div className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
                <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("People using FloBrain")}</p>
                <p className="text-3xl font-semibold tabular-nums">{a.active_users ?? tr("Fewer than {n}", { n: a.min_users })}</p>
              </div>
            </div>
            <Section title={tr("Most used screens")}>
              {a.pages.length ? (
                <table className="w-full text-sm">
                  <thead className="text-start text-[color:var(--fb-v2-text-muted)]">
                    <tr>
                      <th className="py-1 text-start font-medium">{tr("Screen")}</th>
                      <th className="py-1 text-end font-medium">{tr("Views")}</th>
                      <th className="py-1 text-end font-medium">{tr("People")}</th>
                      <th className="w-1/3" />
                    </tr>
                  </thead>
                  <tbody>
                    {a.pages.map((p) => (
                      <tr key={p.page} className="border-t border-[color:var(--fb-v2-border)]">
                        <td className="py-1.5">
                          <code>{p.page}</code>
                        </td>
                        <td className="py-1.5 text-end tabular-nums">{p.events}</td>
                        <td className="py-1.5 text-end tabular-nums">{p.users}</td>
                        <td className="ps-3">
                          <Bar value={p.events} max={maxPage} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Not enough people yet to show screens without identifying anyone.")}</p>
              )}
              {a.hidden.pages ? <p className="mt-2 text-xs text-[color:var(--fb-v2-text-muted)]">{tr("{n} screens hidden because fewer than {min} people used them.", { n: a.hidden.pages, min: a.min_users })}</p> : null}
            </Section>
            <Section title={tr("Views per day")}>
              {a.by_day.length ? (
                <ul className="space-y-1 text-sm">
                  {a.by_day.map((d) => (
                    <li key={d.day} className="grid grid-cols-[7rem_4rem_1fr] items-center gap-3">
                      <span className="tabular-nums">{new Date(`${d.day}T00:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric", weekday: "short" })}</span>
                      <span className="text-end tabular-nums">{d.events}</span>
                      <Bar value={d.events} max={maxDay} />
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("No days with five or more people yet.")}</p>
              )}
            </Section>
            {a.features.length ? (
              <Section title={tr("Features used")}>
                <Rows>
                  {a.features.map((f) => (
                    <Row key={f.feature}>
                      <code className="text-sm">{f.feature}</code>
                      <span className="text-sm tabular-nums">{tr("{n} uses by {people} people", { n: f.events, people: f.users })}</span>
                    </Row>
                  ))}
                </Rows>
              </Section>
            ) : null}
          </>
        ) : null}
      </ScreenBody>
    </>
  );
}

function Mine({ orgId }: { orgId: string }) {
  const tr = useTr();
  const items = useOrgData<{ results: Item[] }>(orgId, "/feedback?page_size=50", { list: true });
  return (
    <ScreenBody state={items.state} error={items.error} emptyLabel={tr("You haven't sent anything yet. Use Report a problem at the top of any page.")} onRetry={items.reload}>
      <Rows>
        {(items.data?.results ?? []).map((item) => (
          <Row key={item.id} className="items-start">
            <div className="min-w-0">
              <p className="whitespace-pre-wrap">{item.text}</p>
              <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
                {tr(KIND[item.kind])} · {item.page || "/"} · {when(item.created_at)}
              </p>
            </div>
            <Badge tone={item.status === "closed" ? "good" : item.status === "triaged" ? "accent" : "waiting"}>{tr(STATUS[item.status])}</Badge>
          </Row>
        ))}
      </Rows>
    </ScreenBody>
  );
}
