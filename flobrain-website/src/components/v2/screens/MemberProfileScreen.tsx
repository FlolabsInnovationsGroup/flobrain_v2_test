"use client";

import Link from "next/link";
import { useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { ConfirmButton } from "@/components/v2/shell/ConfirmButton";
import { Button } from "@/components/v2/ui/button";
import { Avatar, Badge, Notice, PageHeader, Row, Rows, Section } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText } from "@/lib/v2/api";
import { useLowBandwidth } from "@/lib/v2/LayoutContext";
import {
  displayName,
  EMPLOYMENT_STATUSES,
  PRESENCE_LABEL,
  STATUS_LABEL,
  statusChangeWarning,
  statusTone,
  type Member,
} from "@/lib/v2/screens/people";
import { useOrgData } from "@/lib/v2/useOrgData";

export function MemberProfileScreen({ orgSlug, userId }: { orgSlug: string; userId: string }) {
  const tr = useTr();
  const { orgId, access } = useAccess();
  const low = useLowBandwidth();
  const { data: m, state, error, reload } = useOrgData<Member>(orgId, `/members/${userId}`);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const isMe = access?.user_id === userId;

  async function patch(body: Record<string, unknown>, done: string) {
    setMessage(null);
    try {
      await api.patch(`/orgs/${orgId}/members/${userId}`, body);
      setMessage({ kind: "ok", text: done });
      reload();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  return (
    <div className="max-w-4xl">
      <p className="mb-2 text-sm">
        <Link href={`/w/${orgSlug}/directory`} className="hover:underline">
          {tr("Directory")}
        </Link>
      </p>
      <ScreenBody state={state} error={error} emptyLabel={tr("Member not found")} onRetry={reload}>
        {m ? (
          <>
            <div className="mb-6 flex flex-wrap items-start gap-4">
              {low ? null : <Avatar name={displayName(m)} size={56} />}
              <div className="min-w-0 flex-1">
                <PageHeader
                  title={displayName(m)}
                  intro={m.about_me || undefined}
                  action={
                    isMe ? (
                      <Button asChild variant="outline">
                        <Link href={`/w/${orgSlug}/settings/profile`}>{tr("Edit my profile")}</Link>
                      </Button>
                    ) : undefined
                  }
                />
                <p className="-mt-4 flex flex-wrap items-center gap-2 text-sm">
                  {m.org_role !== "member" ? <Badge tone="accent">{tr(m.org_role === "owner" ? "Owner" : "Admin")}</Badge> : null}
                  <Badge tone={statusTone(m.employment_status)}>{tr(STATUS_LABEL[m.employment_status] ?? m.employment_status)}</Badge>
                  <span className="text-[color:var(--fb-v2-text-muted)]">{tr(PRESENCE_LABEL[m.presence] ?? m.presence)}</span>
                  {m.timezone ? <span className="text-[color:var(--fb-v2-text-muted)]">· {m.timezone}</span> : null}
                </p>
              </div>
            </div>
            {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}

            <div className="grid gap-x-8 md:grid-cols-2">
              <Section title={tr("Contact")}>
                <dl className="space-y-1 text-sm">
                  {m.email ? <Pair label={tr("Email")} value={<a className="hover:underline" href={`mailto:${m.email}`}>{m.email}</a>} /> : null}
                  {m.phone ? <Pair label={tr("Phone")} value={<a className="hover:underline" href={`tel:${m.phone}`}>{m.phone}</a>} /> : null}
                  {m.discord_handle ? <Pair label={tr("Discord")} value={m.discord_handle} /> : null}
                  {m.linkedin_url && /^https?:\/\//.test(m.linkedin_url) ? (
                    <Pair label={tr("LinkedIn")} value={<a className="hover:underline" href={m.linkedin_url} target="_blank" rel="noopener noreferrer">{tr("Profile")}</a>} />
                  ) : null}
                  {!m.email && !m.phone && !m.discord_handle && !m.linkedin_url ? (
                    <p className="text-[color:var(--fb-v2-text-muted)]">{tr("No contact details you can see.")}</p>
                  ) : null}
                </dl>
              </Section>
              <Section title={tr("Teams")}>
                {m.team_roles?.length ? (
                  <ul className="space-y-1 text-sm">
                    {m.team_roles.map((t) => (
                      <li key={t.id}>
                        {t.name} {t.role === "lead" ? <Badge tone="accent">{tr("Lead")}</Badge> : null}
                        {t.is_active === false ? <span className="text-[color:var(--fb-v2-text-muted)]"> ({tr("archived")})</span> : null}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("No team yet")}</p>
                )}
              </Section>
            </div>

            <Section title={tr("Projects")}>
              {m.projects?.length ? (
                <Rows>
                  {m.projects.map((p) => (
                    <Row key={p.id}>
                      <span>{p.name}</span>
                      <span className="flex gap-2">
                        {p.is_lead ? <Badge tone="accent">{tr("Lead")}</Badge> : null}
                        <Badge>{tr(`project|${p.status}`)}</Badge>
                      </span>
                    </Row>
                  ))}
                </Rows>
              ) : (
                <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("No projects you can see.")}</p>
              )}
            </Section>

            {orgId ? <Skills orgId={orgId} member={m} isMe={isMe} onChange={reload} /> : null}

            {m.can?.change_status || m.can?.change_role ? (
              <Manage member={m} canStatus={!!m.can?.change_status} canRole={!!m.can?.change_role} onPatch={patch} />
            ) : null}
          </>
        ) : null}
      </ScreenBody>
    </div>
  );
}

function Pair({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex gap-2">
      <dt className="w-24 shrink-0 text-[color:var(--fb-v2-text-muted)]">{label}</dt>
      <dd className="min-w-0 break-words">{value}</dd>
    </div>
  );
}

function Skills({ orgId, member, isMe, onChange }: { orgId: string; member: Member; isMe: boolean; onChange: () => void }) {
  const tr = useTr();
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const confirmer = !!member.can?.confirm_skills;
  const canAdd = isMe || confirmer;
  const base = `/orgs/${orgId}/members/${member.id}/skills`;

  async function add(skill: string) {
    setError("");
    try {
      await api.post(base, { name: skill });
      setName("");
      onChange();
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function remove(id: number) {
    setError("");
    try {
      await api.del(`${base}/${id}`);
      onChange();
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <Section title={tr("Skills")}>
      <p className="mb-2 text-sm text-[color:var(--fb-v2-text-muted)]">
        {isMe
          ? tr("Skills you add show as not confirmed until a lead of your team or an admin confirms them.")
          : confirmer
            ? tr("Skills you add or confirm count as confirmed for task suggestions.")
            : tr("Skills help leads find the right person for a task.")}
      </p>
      {member.skills?.length ? (
        <ul className="mb-3 flex flex-wrap gap-2">
          {member.skills.map((s) => (
            <li key={s.id} className="inline-flex items-center gap-1 rounded-full px-3 py-1 text-sm ring-1 ring-inset ring-[color:var(--fb-v2-border)]">
              {s.name}
              {s.confirmed ? <Badge tone="good">{tr("Confirmed")}</Badge> : <span className="text-xs text-[color:var(--fb-v2-text-muted)]">{tr("Not confirmed")}</span>}
              {!s.confirmed && confirmer ? (
                <button type="button" className="ms-1 text-xs underline" onClick={() => add(s.name)}>
                  {tr("Confirm")}
                </button>
              ) : null}
              {isMe || confirmer ? (
                <button type="button" className="ms-1 text-xs" aria-label={tr("Remove {skill}", { skill: s.name })} onClick={() => remove(s.id)}>
                  ×
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mb-3 text-sm text-[color:var(--fb-v2-text-muted)]">{tr("No skills yet")}</p>
      )}
      {canAdd ? (
        <form
          className="flex max-w-md gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (name.trim()) void add(name.trim());
          }}
        >
          <label className="flex-1">
            <span className="sr-only">{tr("Skill")}</span>
            <input className="v2-input" value={name} maxLength={60} onChange={(e) => setName(e.target.value)} placeholder={tr("Add a skill, like Figma")} />
          </label>
          <Button type="submit" variant="outline">
            {tr("Add")}
          </Button>
        </form>
      ) : null}
      {error ? <Notice kind="error">{error}</Notice> : null}
    </Section>
  );
}

function Manage({
  member,
  canStatus,
  canRole,
  onPatch,
}: {
  member: Member;
  canStatus: boolean;
  canRole: boolean;
  onPatch: (body: Record<string, unknown>, done: string) => Promise<void>;
}) {
  const tr = useTr();
  const [next, setNext] = useState(member.employment_status === "active" ? "paused" : "active");
  const name = displayName(member);
  const roleTarget = member.org_role === "admin" ? "member" : "admin";

  return (
    <Section title={tr("Manage")}>
      <Rows>
        {canStatus ? (
          <Row className="items-start">
            <div className="max-w-md">
              <p className="font-medium">{tr("Status")}</p>
              <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
                {tr("Now: {status}", { status: tr(STATUS_LABEL[member.employment_status] ?? member.employment_status) })}
                {member.status_reason ? ` · ${member.status_reason}` : ""}
              </p>
            </div>
            <div className="flex w-full max-w-sm flex-col gap-2">
              <label className="text-sm">
                <span className="sr-only">{tr("New status")}</span>
                <select className="v2-input" value={next} onChange={(e) => setNext(e.target.value)}>
                  {EMPLOYMENT_STATUSES.filter((s) => s !== member.employment_status).map((s) => (
                    <option key={s} value={s}>
                      {tr(STATUS_LABEL[s])}
                    </option>
                  ))}
                </select>
              </label>
              <ConfirmButton
                label={tr("Change status")}
                variant={next === "terminated" ? "danger" : "outline"}
                withReason
                question={tr("Set {name} to {status}? {warning}", { name, status: tr(STATUS_LABEL[next]), warning: tr(statusChangeWarning(next)) })}
                onConfirm={(reason) => onPatch({ employment_status: next, reason }, tr("Status changed."))}
              />
            </div>
          </Row>
        ) : null}
        {canRole ? (
          <Row className="items-start">
            <div className="max-w-md">
              <p className="font-medium">{tr("Organization role")}</p>
              <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
                {member.org_role === "admin"
                  ? tr("Admins manage members, access and settings.")
                  : tr("Members work in their rooms and teams. Admins manage the organization.")}
              </p>
            </div>
            <ConfirmButton
              label={roleTarget === "admin" ? tr("Make admin") : tr("Make member")}
              question={
                roleTarget === "admin"
                  ? tr("Make {name} an admin? They can manage members, access and settings.", { name })
                  : tr("Make {name} a member? They lose admin rights.", { name })
              }
              onConfirm={() => onPatch({ org_role: roleTarget }, tr("Role changed."))}
            />
          </Row>
        ) : null}
      </Rows>
    </Section>
  );
}
