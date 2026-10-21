"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Notice, PageHeader } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { roleLabel } from "@/lib/v2/access";
import { useAccess } from "@/lib/v2/AccessContext";
import { errorText } from "@/lib/v2/api";
import { demoSignIn } from "@/lib/v2/demo";
import { cn } from "@/lib/utils";

type Stop = { path: string; title: string; try: string; role: "owner" | "admin" | "lead" | "member" };

/** The guided path: a real sequence, so the stops are numbered. Each stop says whose seat to use. */
const STOPS: Stop[] = [
  { role: "member", path: "/tasks", title: "Tasks", try: "Drag “Fix login timeout on Android” and see why it's blocked." },
  { role: "member", path: "/time", title: "Time", try: "Start the timer from the top bar, stop it, then submit your week for approval." },
  { role: "member", path: "/rooms", title: "Rooms and docs", try: "Open the Mobile app launch room, mention @Layla in chat, then open Docs › Launch plan, edit it and look at its history." },
  { role: "member", path: "/ask", title: "Ask the org", try: "Ask “What is the launch plan?” and open a source." },
  { role: "member", path: "/buddies", title: "Buddies", try: "Open Release notes helper and press “Propose a task”." },
  { role: "member", path: "/approvals", title: "Approvals", try: "Approve the task the buddy proposed. It runs with your permissions." },
  { role: "member", path: "/learning", title: "Learning", try: "Open Masterclasses (synced from a demo Notion database) and your cohort's progress." },
  { role: "member", path: "/studio", title: "Content Studio", try: "Create a 30-second video project for YouTube." },
  { role: "member", path: "/rooms", title: "Meetings", try: "Open the Mobile app launch room, then Meetings. Join “Launch standup (live now)”, record for a moment, stop, and read the transcript by speaker." },
  { role: "member", path: "/insights", title: "Insights", try: "See your month in numbers: tasks, hours and meetings." },
  { role: "member", path: "/privacy", title: "Privacy", try: "See who can see your time, keep your insights personal, and download a copy of your data." },
  { role: "lead", path: "/reports", title: "Team reports", try: "Draft the Engineering weekly report, then post it." },
  { role: "lead", path: "/insights", title: "Team insights", try: "Compare your team's tasks and hours. People who keep their insights personal are left out." },
  { role: "lead", path: "/time", title: "Approve time", try: "Approve the entry waiting for you, or send it back with a note." },
  { role: "lead", path: "/mission-control", title: "Mission Control", try: "See your team's capacity, blocked work and deadlines." },
  { role: "lead", path: "/agents", title: "Agents", try: "Run the Monday release-notes agent now." },
  { role: "admin", path: "/rooms", title: "Meeting assistant", try: "In a room's Meetings, invite the assistant to a Zoom link. It joins, records and leaves a summary with action items." },
  { role: "admin", path: "/marketplace", title: "Marketplace", try: "Approve Youssef's buddy so everyone can install it." },
  { role: "admin", path: "/directory", title: "People", try: "Confirm one of the two people waiting from HR into a team." },
  { role: "admin", path: "/settings/budgets", title: "AI budgets", try: "Engineering is at 85% of its AI budget. Switch it to a cheaper model when it runs out." },
  { role: "admin", path: "/settings/external-agents", title: "External agents", try: "The demo partner agent answered with an instruction to delete tasks. See that it was quoted and ignored." },
  { role: "admin", path: "/settings/access", title: "Access", try: "Grant a permission for a week and see it in the audit log." },
  { role: "admin", path: "/settings/retention", title: "Deletion requests", try: "Sara asked to delete her data. Decide her request." },
  { role: "owner", path: "/settings/ai-policy", title: "AI policy", try: "Switch to self-hosted models only and see what changes." },
  { role: "owner", path: "/settings/sso", title: "SSO and provisioning", try: "SAML is connected to a demo identity provider. Sign out, choose “Sign in with SSO” with owner@demo.flobrain.example, and pick who signs in." },
  { role: "owner", path: "/settings/billing", title: "Billing", try: "See seats and this month's AI cost." },
  { role: "owner", path: "/settings/export", title: "Export", try: "Export the org's memory and download the zip." },
  { role: "owner", path: "/settings/developer", title: "API and webhooks", try: "Create a read-only token for another tool, then send a test webhook to the demo inbox." },
  { role: "owner", path: "/settings/incidents", title: "Status and incidents", try: "Open an incident, post an update, then see it on the public status page." },
];

const WHO: Record<string, string> = { owner: "Nadia (owner)", admin: "Omar (admin)", lead: "Layla (team lead)", member: "Youssef (member)" };

export default function TourPage() {
  const { orgSlug } = useParams<{ orgSlug: string }>();
  const { access } = useAccess();
  const tr = useTr();
  const [error, setError] = useState("");
  const me = access?.demo_role ?? "";

  async function go(stop: Stop) {
    if (stop.role === me) {
      window.location.assign(`/w/${orgSlug}${stop.path}`);
      return;
    }
    try {
      window.location.assign(await demoSignIn(stop.role, stop.path));
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <div className="max-w-3xl">
      <PageHeader
        title={tr("Guided tour")}
        intro={tr("{n} stops through FloBrain at Nile Labs. Each stop opens in the right person's seat, so you see exactly what they see. You are the {role} now.", {
          n: STOPS.length,
          role: roleLabel(access).toLowerCase(),
        })}
      />
      {error ? <Notice kind="error">{error}</Notice> : null}
      <ol className="space-y-2">
        {STOPS.map((stop, i) => (
          <li key={stop.path} className="flex items-start gap-4 rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
            <span className="mt-0.5 w-6 shrink-0 text-end font-semibold text-[color:var(--fb-v2-accent)]">{i + 1}</span>
            <div className="min-w-0 flex-1">
              <p className="font-medium">{tr(stop.title)}</p>
              <p className="text-sm">{tr(stop.try)}</p>
              <p className="mt-1 text-xs text-[color:var(--fb-v2-text-muted)]">{tr("As {who}", { who: tr(WHO[stop.role]) })}</p>
            </div>
            <Button variant={stop.role === me ? "default" : "outline"} className={cn("shrink-0")} onClick={() => go(stop)}>
              {tr(stop.role === me ? "Open" : "Switch and open")}
            </Button>
          </li>
        ))}
      </ol>
      <p className="mt-6 text-sm text-[color:var(--fb-v2-text-muted)]">
        {tr("Changed too much? Use “Start the demo over” in the bar at the top.")}{" "}
        <Link className="underline" href={`/w/${orgSlug}`}>
          {tr("Back to home")}
        </Link>
      </p>
    </div>
  );
}
