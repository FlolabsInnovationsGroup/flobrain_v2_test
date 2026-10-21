"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { ConfirmButton } from "@/components/v2/shell/ConfirmButton";
import { Button } from "@/components/v2/ui/button";
import { Avatar, Badge, Field, Notice, PageHeader, Row, Rows, Section, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { has, isLead } from "@/lib/v2/access";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText } from "@/lib/v2/api";
import { useLowBandwidth } from "@/lib/v2/LayoutContext";
import {
  displayName,
  EMPTY_FILTERS,
  memberQuery,
  pageCount,
  PRESENCE_LABEL,
  STATUS_FILTERS,
  STATUS_LABEL,
  statusTone,
  type DirectoryFilters,
  type Member,
} from "@/lib/v2/screens/people";
import { useOrgData } from "@/lib/v2/useOrgData";
import { cn } from "@/lib/utils";

type Team = { id: string; name: string; is_active: boolean; my_role: string | null };
type Page = { count: number; results: Member[] };
type Pending = { id: string; full_name: string; username: string | null; email?: string; source: string; reference: string; created_at: string; teams: { id: string; name: string }[] };

export function DirectoryScreen({ orgSlug }: { orgSlug: string }) {
  const tr = useTr();
  const { orgId, access } = useAccess();
  const low = useLowBandwidth();
  const [filters, setFilters] = useState<DirectoryFilters>(EMPTY_FILTERS);
  const [search, setSearch] = useState("");
  const [showRegister, setShowRegister] = useState(false);
  const query = useMemo(() => new URLSearchParams(memberQuery(filters)).toString(), [filters]);
  const members = useOrgData<Page>(orgId, `/members?${query}`, { list: true });
  const teams = useOrgData<Team[]>(orgId, "/teams?scope=all");
  const manager = has(access, "org.members.manage");
  const lead = isLead(access);
  const pending = useOrgData<Pending[]>(orgId, manager || lead ? "/pending-members" : null);
  const activeTeams = (teams.data ?? []).filter((t) => t.is_active);
  const count = members.data?.count ?? 0;
  const pages = pageCount(count);
  const set = (next: Partial<DirectoryFilters>) => setFilters((f) => ({ ...f, ...next, page: next.page ?? 1 }));

  return (
    <div className="max-w-5xl">
      <PageHeader
        title={tr("Directory")}
        intro={tr("Everyone in your organization, their teams and whether they are around.")}
        action={
          manager || lead ? (
            <Button onClick={() => setShowRegister((v) => !v)} variant={showRegister ? "outline" : "default"}>
              {showRegister ? tr("Close") : tr("Register a member")}
            </Button>
          ) : undefined
        }
      />

      {showRegister && orgId ? (
        <RegisterForm
          orgId={orgId}
          teams={activeTeams.filter((t) => manager || t.my_role === "lead")}
          canChooseRole={access?.org_role === "owner" || access?.org_role === "admin"}
          requireTeam={!manager}
          onDone={() => {
            members.reload();
            pending.reload();
          }}
        />
      ) : null}

      {(manager || lead) && orgId && (pending.data?.length ?? 0) > 0 ? (
        <PendingSection orgId={orgId} rows={pending.data ?? []} teams={activeTeams.filter((t) => manager || t.my_role === "lead")} canDecline={manager} onChange={() => { pending.reload(); members.reload(); }} />
      ) : null}

      <form
        className="mb-4 flex flex-wrap items-end gap-3"
        role="search"
        onSubmit={(e) => {
          e.preventDefault();
          set({ q: search });
        }}
      >
        <label className="min-w-48 flex-1 text-sm">
          <span className="mb-1 block font-medium">{tr("Search members")}</span>
          <input className="v2-input" value={search} onChange={(e) => setSearch(e.target.value)} onBlur={() => set({ q: search })} placeholder={tr("Name")} />
        </label>
        <label className="text-sm">
          <span className="mb-1 block font-medium">{tr("Team")}</span>
          <select className="v2-input" value={filters.team} onChange={(e) => set({ team: e.target.value })}>
            <option value="">{tr("All teams")}</option>
            {(teams.data ?? []).map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
                {t.is_active ? "" : ` (${tr("archived")})`}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          <span className="mb-1 block font-medium">{tr("Role")}</span>
          <select className="v2-input" value={filters.role} onChange={(e) => set({ role: e.target.value })}>
            <option value="">{tr("Any role")}</option>
            <option value="owner">{tr("Owner")}</option>
            <option value="admin">{tr("Admin")}</option>
            <option value="lead">{tr("Team lead")}</option>
            <option value="member">{tr("Member")}</option>
          </select>
        </label>
        <label className="text-sm">
          <span className="mb-1 block font-medium">{tr("Skill")}</span>
          <input className="v2-input w-36" value={filters.skill} onChange={(e) => set({ skill: e.target.value })} placeholder={tr("For example Python")} />
        </label>
        <button type="submit" className="sr-only">
          {tr("Search")}
        </button>
      </form>

      <div role="radiogroup" aria-label={tr("Status")} className="mb-4 flex flex-wrap gap-1">
        {STATUS_FILTERS.map((s) => (
          <button
            key={s.value}
            type="button"
            role="radio"
            aria-checked={filters.status === s.value}
            onClick={() => set({ status: s.value })}
            className={cn(
              "rounded-full px-3 py-1 text-sm ring-1 ring-inset ring-[color:var(--fb-v2-border)]",
              filters.status === s.value && "bg-[color:var(--fb-v2-accent)] text-white ring-transparent",
            )}
          >
            {tr(s.label)}
          </button>
        ))}
      </div>

      <ScreenBody state={members.state} error={members.error} emptyLabel={tr("Nobody matches these filters.")} onRetry={members.reload}>
        <Rows>
          {(members.data?.results ?? []).map((m) => (
            <Row key={m.id}>
              <div className="flex min-w-0 items-center gap-3">
                {low ? null : <Avatar name={displayName(m)} />}
                <div className="min-w-0">
                  <Link href={`/w/${orgSlug}/members/${m.id}`} className="font-medium hover:underline">
                    {displayName(m)}
                  </Link>
                  <p className="truncate text-sm text-[color:var(--fb-v2-text-muted)]">
                    {(m.team_roles ?? []).map((t) => (t.role === "lead" ? tr("{team} (lead)", { team: t.name }) : t.name)).join(", ") || tr("No team yet")}
                    {m.email ? ` · ${m.email}` : ""}
                  </p>
                  {m.skills?.length ? (
                    <p className="mt-1 flex flex-wrap gap-1">
                      {m.skills.slice(0, 5).map((s) => (
                        <Badge key={s.id}>{s.name}</Badge>
                      ))}
                    </p>
                  ) : null}
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-2 text-sm">
                {m.org_role !== "member" ? <Badge tone="accent">{tr(m.org_role === "owner" ? "Owner" : "Admin")}</Badge> : null}
                {m.employment_status !== "active" ? (
                  <Badge tone={statusTone(m.employment_status)}>{tr(STATUS_LABEL[m.employment_status] ?? m.employment_status)}</Badge>
                ) : (
                  <span className="text-[color:var(--fb-v2-text-muted)]">{tr(PRESENCE_LABEL[m.presence] ?? m.presence)}</span>
                )}
              </div>
            </Row>
          ))}
        </Rows>
        {pages > 1 ? (
          <nav aria-label={tr("Pages")} className="mt-4 flex items-center gap-3 text-sm">
            <Button variant="outline" disabled={filters.page <= 1} onClick={() => set({ page: filters.page - 1 })}>
              {tr("Previous")}
            </Button>
            <span>{tr("Page {page} of {pages}", { page: filters.page, pages })}</span>
            <Button variant="outline" disabled={filters.page >= pages} onClick={() => set({ page: filters.page + 1 })}>
              {tr("Next")}
            </Button>
          </nav>
        ) : null}
      </ScreenBody>
    </div>
  );
}

function RegisterForm({
  orgId,
  teams,
  canChooseRole,
  requireTeam,
  onDone,
}: {
  orgId: string;
  teams: Team[];
  canChooseRole: boolean;
  requireTeam: boolean;
  onDone: () => void;
}) {
  const tr = useTr();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [team, setTeam] = useState("");
  const [role, setRole] = useState("member");
  const [activate, setActivate] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      await api.post(`/orgs/${orgId}/members`, {
        username: name,
        email,
        ...(team ? { team_id: team } : {}),
        ...(canChooseRole ? { org_role: role } : {}),
        activate,
      });
      setMessage({
        kind: "ok",
        text: activate
          ? tr("{email} is registered. They get an email with a temporary password.", { email })
          : tr("{email} is registered and waits for confirmation below.", { email }),
      });
      setName("");
      setEmail("");
      onDone();
    } catch (err) {
      setMessage({ kind: "error", text: tr("Could not register {email}: {reason}. Check the details and try again.", { email, reason: errorText(err) }) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section title={tr("Register a member")}>
      <form onSubmit={submit} className="grid gap-x-4 rounded-xl bg-[color:var(--fb-v2-surface)] p-4 md:grid-cols-2">
        <Field label={tr("Full name")}>
          <input className="v2-input" value={name} onChange={(e) => setName(e.target.value)} required maxLength={150} />
        </Field>
        <Field label={tr("Work email")}>
          <input className="v2-input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </Field>
        <Field label={tr("Team")} hint={requireTeam ? tr("You can register people into teams you lead.") : undefined}>
          <select className="v2-input" value={team} onChange={(e) => setTeam(e.target.value)} required={requireTeam}>
            <option value="">{requireTeam ? tr("Pick a team") : tr("No team for now")}</option>
            {teams.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
        </Field>
        {canChooseRole ? (
          <Field label={tr("Role")}>
            <select className="v2-input" value={role} onChange={(e) => setRole(e.target.value)}>
              <option value="member">{tr("Member")}</option>
              <option value="admin">{tr("Admin")}</option>
            </select>
          </Field>
        ) : null}
        <label className="mb-4 flex items-center gap-2 text-sm md:col-span-2">
          <input type="checkbox" checked={activate} onChange={(e) => setActivate(e.target.checked)} />
          {tr("Activate now (otherwise they wait for confirmation)")}
        </label>
        <div className="md:col-span-2">
          <Button type="submit" disabled={busy}>
            {busy ? tr("Registering") : tr("Register")}
          </Button>
          {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
        </div>
      </form>
    </Section>
  );
}

function PendingSection({
  orgId,
  rows,
  teams,
  canDecline,
  onChange,
}: {
  orgId: string;
  rows: Pending[];
  teams: Team[];
  canDecline: boolean;
  onChange: () => void;
}) {
  const tr = useTr();
  const [choice, setChoice] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  async function decide(row: Pending, decision: "confirm" | "decline", reason = "") {
    setMessage(null);
    try {
      await api.post(`/orgs/${orgId}/pending-members/${row.id}/${decision}`, decision === "confirm" ? { team_id: choice[row.id] ?? row.teams[0]?.id } : { reason });
      setMessage({ kind: "ok", text: decision === "confirm" ? tr("{name} is active now.", { name: row.full_name }) : tr("{name} was declined.", { name: row.full_name }) });
      onChange();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  return (
    <Section title={tr("Waiting for confirmation")} aside={<Badge tone="waiting">{rows.length}</Badge>}>
      <p className="mb-3 text-sm text-[color:var(--fb-v2-text-muted)]">
        {tr("New people from the HR pipeline, or registered without activation. Pick their team to let them sign in.")}
      </p>
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      <Rows>
        {rows.map((row) => (
          <Row key={row.id} className="items-start">
            <div className="min-w-0">
              <p className="font-medium">{row.full_name || row.username}</p>
              <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
                {row.source === "registered" ? tr("Registered") : tr("From HR")}
                {row.reference ? ` · ${row.reference}` : ""}
                {row.email ? ` · ${row.email}` : ""} · {when(row.created_at)}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <label className="text-sm">
                <span className="sr-only">{tr("Team")}</span>
                <select
                  className="v2-input w-44"
                  value={choice[row.id] ?? row.teams[0]?.id ?? ""}
                  onChange={(e) => setChoice((c) => ({ ...c, [row.id]: e.target.value }))}
                >
                  <option value="">{tr("Pick a team")}</option>
                  {teams.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name}
                    </option>
                  ))}
                </select>
              </label>
              <Button
                disabled={!(choice[row.id] ?? row.teams[0]?.id)}
                onClick={() => decide(row, "confirm")}
              >
                {tr("Confirm and activate")}
              </Button>
              {canDecline ? (
                <ConfirmButton
                  label={tr("Decline")}
                  variant="danger"
                  withReason
                  question={tr("Decline {name}? They won't be able to sign in.", { name: row.full_name })}
                  onConfirm={(reason) => decide(row, "decline", reason)}
                />
              ) : null}
            </div>
          </Row>
        ))}
      </Rows>
    </Section>
  );
}
