"use client";

import { useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Badge, Field, Notice, Row, Rows, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, errorText } from "@/lib/v2/api";

import type { Card, Report } from "./types";

type Option = { id: string; name: string };

export const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

/** "Weekly on Monday at 08:00 UTC" / "Monthly on day 1 at 08:00 UTC". */
export function scheduleText(r: Pick<Report, "cadence" | "weekday" | "day_of_month" | "hour">, tr: (t: string, v?: Record<string, string | number>) => string) {
  const time = `${String(r.hour).padStart(2, "0")}:00`;
  return r.cadence === "weekly"
    ? tr("Weekly on {day} at {time} UTC", { day: tr(WEEKDAYS[r.weekday] ?? "Monday"), time })
    : tr("Monthly on day {day} at {time} UTC", { day: r.day_of_month, time });
}

export function ReportsPanel({
  orgId,
  reports,
  cards,
  rooms,
  members,
  userId,
  isAdmin,
  focus,
  onChange,
}: {
  orgId: string;
  reports: Report[];
  cards: Card[];
  rooms: Option[];
  members: Option[];
  userId: string | null;
  isAdmin: boolean;
  focus?: string | null;
  onChange: () => void;
}) {
  const tr = useTr();
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [name, setName] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const [cadence, setCadence] = useState<"weekly" | "monthly">("weekly");
  const [weekday, setWeekday] = useState(0);
  const [day, setDay] = useState(1);
  const [hour, setHour] = useState(8);
  const [room, setRoom] = useState("");
  const [recipients, setRecipients] = useState<string[]>([]);
  const titleOf = (id: string) => cards.find((c) => c.id === id)?.title ?? tr("A card you can't see");

  async function act(fn: () => Promise<unknown>, ok: string) {
    setMessage(null);
    try {
      await fn();
      setMessage({ kind: "ok", text: ok });
      onChange();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  return (
    <div className="flex flex-col gap-6">
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      {reports.length ? (
        <Rows>
          {reports.map((r) => {
            const mine = r.created_by === userId || isAdmin;
            return (
              <Row key={r.id} className={focus === r.id ? "ring-1 ring-inset ring-[color:var(--fb-v2-accent)]" : ""}>
                <div className="min-w-0 flex-1 basis-64">
                  <p className="flex flex-wrap items-center gap-2 font-medium">
                    {r.name}
                    {!r.enabled ? <Badge>{tr("Paused")}</Badge> : null}
                    {r.last_status === "failed" ? <Badge tone="bad">{tr("Last run failed")}</Badge> : r.last_status === "partial" ? <Badge tone="bad">{tr("Some cards failed")}</Badge> : null}
                  </p>
                  <p className="text-xs text-[color:var(--fb-v2-text-muted)]">
                    {scheduleText(r, tr)}. {r.next_run_at && r.enabled ? tr("Next: {when}.", { when: when(r.next_run_at) }) : null}{" "}
                    {r.room ? tr("Also posted in {room}.", { room: rooms.find((x) => x.id === r.room)?.name ?? tr("a room") }) : null}
                  </p>
                  <ul className="mt-2 flex flex-col gap-1 text-sm">
                    {(r.last_results.length ? r.last_results : r.cards.map((c) => ({ card: c, title: titleOf(c), headline: "", error: "" }))).map((x) => (
                      <li key={x.card} className="flex flex-wrap gap-x-2">
                        <span>{x.title}</span>
                        {x.headline ? <span className="tabular-nums text-[color:var(--fb-v2-text-muted)]">{x.headline}</span> : null}
                        {x.error ? <span className="text-[color:var(--fb-v2-error)]">{tr("Could not refresh")}</span> : null}
                      </li>
                    ))}
                  </ul>
                  {r.last_run_at ? <p className="mt-1 text-xs text-[color:var(--fb-v2-text-faint)]">{tr("Last sent {when}", { when: when(r.last_run_at) })}</p> : null}
                </div>
                {mine ? (
                  <div className="flex flex-wrap gap-2">
                    <Button variant="outline" onClick={() => act(() => api.post(`/orgs/${orgId}/data/reports/${r.id}/run`), tr("Sent with fresh numbers."))}>
                      {tr("Send now")}
                    </Button>
                    <Button variant="ghost" onClick={() => act(() => api.patch(`/orgs/${orgId}/data/reports/${r.id}`, { enabled: !r.enabled }), r.enabled ? tr("Paused.") : tr("Resumed."))}>
                      {r.enabled ? tr("Pause") : tr("Resume")}
                    </Button>
                    <Button variant="danger" onClick={() => act(() => api.del(`/orgs/${orgId}/data/reports/${r.id}`), tr("Report deleted."))}>
                      {tr("Delete")}
                    </Button>
                  </div>
                ) : null}
              </Row>
            );
          })}
        </Rows>
      ) : (
        <Notice>{tr("No reports yet. Save a few cards, then schedule them here.")}</Notice>
      )}

      <form
        className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4"
        onSubmit={(e) => {
          e.preventDefault();
          act(
            () =>
              api.post(`/orgs/${orgId}/data/reports`, {
                name,
                cards: picked,
                cadence,
                weekday,
                day_of_month: day,
                hour,
                recipients,
                ...(room ? { room } : {}),
              }),
            tr("Report scheduled."),
          ).then(() => {
            setName("");
            setPicked([]);
          });
        }}
      >
        <h3 className="mb-3 font-semibold">{tr("Schedule a report")}</h3>
        {cards.length ? (
          <>
            <Field label={tr("Name")}>
              <input className="v2-input w-full" required maxLength={120} value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
            <fieldset className="mb-4 text-sm">
              <legend className="mb-1 font-medium">{tr("Cards")}</legend>
              <div className="flex flex-col gap-1">
                {cards.map((c) => (
                  <label key={c.id} className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={picked.includes(c.id)}
                      onChange={(e) => setPicked((all) => (e.target.checked ? [...all, c.id] : all.filter((x) => x !== c.id)))}
                    />
                    {c.title} <span className="text-xs text-[color:var(--fb-v2-text-muted)]">{c.dataset_name}</span>
                  </label>
                ))}
              </div>
            </fieldset>
            <div className="grid gap-x-4 sm:grid-cols-3">
              <Field label={tr("How often")}>
                <select className="v2-input w-full" value={cadence} onChange={(e) => setCadence(e.target.value as "weekly" | "monthly")}>
                  <option value="weekly">{tr("Weekly")}</option>
                  <option value="monthly">{tr("Monthly")}</option>
                </select>
              </Field>
              {cadence === "weekly" ? (
                <Field label={tr("Day")}>
                  <select className="v2-input w-full" value={weekday} onChange={(e) => setWeekday(Number(e.target.value))}>
                    {WEEKDAYS.map((d, i) => (
                      <option key={d} value={i}>
                        {tr(d)}
                      </option>
                    ))}
                  </select>
                </Field>
              ) : (
                <Field label={tr("Day of the month")}>
                  <input className="v2-input w-full" type="number" min={1} max={28} value={day} onChange={(e) => setDay(Number(e.target.value))} />
                </Field>
              )}
              <Field label={tr("Hour (UTC)")}>
                <input className="v2-input w-full" type="number" min={0} max={23} value={hour} onChange={(e) => setHour(Number(e.target.value))} />
              </Field>
            </div>
            {members.length ? (
              <Field label={tr("Also send to")} hint={tr("People only get it if they can see every dataset in it.")}>
                <select
                  multiple
                  className="v2-input h-28 w-full"
                  value={recipients}
                  onChange={(e) => setRecipients([...e.target.selectedOptions].map((o) => o.value))}
                >
                  {members
                    .filter((m) => m.id !== userId)
                    .map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.name}
                      </option>
                    ))}
                </select>
              </Field>
            ) : null}
            <Field label={tr("Post in a room (optional)")} hint={tr("Posted as you, with the fresh numbers.")}>
              <select className="v2-input w-full sm:w-64" value={room} onChange={(e) => setRoom(e.target.value)}>
                <option value="">{tr("No room")}</option>
                {rooms.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name}
                  </option>
                ))}
              </select>
            </Field>
            <Button type="submit" disabled={!picked.length || !name}>
              {tr("Schedule")}
            </Button>
          </>
        ) : (
          <Notice>{tr("Save a question as a card first.")}</Notice>
        )}
      </form>
    </div>
  );
}
