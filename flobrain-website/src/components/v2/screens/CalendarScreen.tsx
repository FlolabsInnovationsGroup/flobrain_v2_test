"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Badge, Notice, PageHeader, Row, Rows, Section } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { groupCalendarByDate, splitOverdue, type CalendarItem } from "@/lib/v2/screens/calendar";
import { peopleLine } from "@/lib/v2/screens/missionControl";
import { priorityLabel, priorityTone } from "@/lib/v2/screens/tasks";
import { mondayOf, shiftWeek, ymd } from "@/lib/v2/screens/time";
import { useAccess } from "@/lib/v2/AccessContext";
import { useOrgData } from "@/lib/v2/useOrgData";

const WEEKS = 4;

function dayTitle(day: string) {
  const d = new Date(+day.slice(0, 4), +day.slice(5, 7) - 1, +day.slice(8, 10));
  return d.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
}

function timeOf(iso?: string) {
  return iso ? new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }) : "";
}

/** Task deadlines and meetings, four weeks at a time. ``?room=`` shows one room's calendar. */
export function CalendarScreen({ orgSlug }: { orgSlug: string }) {
  const tr = useTr();
  const { orgId } = useAccess();
  const room = useSearchParams().get("room");
  const [from, setFrom] = useState(() => mondayOf(new Date()));
  const to = shiftWeek(from, WEEKS);
  const today = ymd(new Date());
  const roomQ = room ? `&room=${room}` : "";
  const items = useOrgData<CalendarItem[]>(orgId, `/calendar?from=${from}&to=${to}${roomQ}`);
  const late = useOrgData<CalendarItem[]>(orgId, `/calendar?to=${today}${roomQ}`);
  const roomInfo = useOrgData<{ name: string }>(orgId, room ? `/rooms/${room}` : null);

  const grouped = useMemo(() => groupCalendarByDate(items.data ?? []), [items.data]);
  const overdue = useMemo(() => splitOverdue(late.data ?? [], today).overdue, [late.data, today]);
  const days = Object.keys(grouped).sort();
  const taskHref = (id: string) => `/w/${orgSlug}/tasks?task=${id}${room ? `&room=${room}` : ""}`;

  function line(item: CalendarItem) {
    if (item.kind === "meeting") {
      return (
        <Row key={item.id}>
          <div>
            <p className="font-medium">{item.title}</p>
            <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
              {timeOf(item.starts_at)}
              {item.room_name ? ` · ${item.room_name}` : ""}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Badge tone="accent">{tr("Meeting")}</Badge>
            {item.room ? (
              <Link className="text-sm underline" href={`/w/${orgSlug}/rooms/${item.room}/meetings`}>
                {tr("Open")}
              </Link>
            ) : null}
          </div>
        </Row>
      );
    }
    return (
      <Row key={item.id}>
        <div>
          <Link className="font-medium hover:underline" href={taskHref(item.id)}>
            {item.title}
          </Link>
          <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{peopleLine(item.people) || tr("Nobody assigned")}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {item.status === "done" ? <Badge tone="good">{tr("Done")}</Badge> : null}
          {item.overdue ? <Badge tone="bad">{tr("Overdue")}</Badge> : null}
          {item.is_blocked ? <Badge tone="bad">{tr("Blocked")}</Badge> : null}
          {item.priority && item.priority !== "normal" ? <Badge tone={priorityTone(item.priority)}>{tr(priorityLabel(item.priority))}</Badge> : null}
        </div>
      </Row>
    );
  }

  return (
    <div className="max-w-5xl">
      <PageHeader
        title={roomInfo.data ? tr("Calendar for {room}", { room: roomInfo.data.name }) : tr("Calendar")}
        intro={tr("Task deadlines and meetings you can see. Open a task to change it.")}
        action={
          <div className="flex flex-wrap items-center gap-2">
            <Button type="button" variant="ghost" onClick={() => setFrom(shiftWeek(from, -WEEKS))}>
              {tr("Earlier")}
            </Button>
            <Button type="button" variant="outline" onClick={() => setFrom(mondayOf(new Date()))}>
              {tr("Today")}
            </Button>
            <Button type="button" variant="ghost" onClick={() => setFrom(shiftWeek(from, WEEKS))}>
              {tr("Later")}
            </Button>
          </div>
        }
      />
      {room ? (
        <Notice>
          {tr("Showing this room's calendar.")}{" "}
          <Link className="underline" href={`/w/${orgSlug}/calendar`}>
            {tr("Show everything")}
          </Link>
        </Notice>
      ) : null}
      {overdue.length ? (
        <Section title={tr("Overdue")}>
          <Rows>{overdue.map(line)}</Rows>
        </Section>
      ) : null}
      <ScreenBody state={items.state} error={items.error || tr("Could not load calendar")} onRetry={items.reload}>
        {days.length === 0 ? <Notice>{tr("Nothing due in these four weeks.")}</Notice> : null}
        {days.map((day) => (
          <Section key={day} title={day === today ? `${tr("Today")}, ${dayTitle(day)}` : dayTitle(day)}>
            <Rows>{grouped[day].map(line)}</Rows>
          </Section>
        ))}
      </ScreenBody>
    </div>
  );
}
