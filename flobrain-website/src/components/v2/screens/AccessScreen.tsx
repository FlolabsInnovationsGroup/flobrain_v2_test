"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { ConfirmButton } from "@/components/v2/shell/ConfirmButton";
import { Button } from "@/components/v2/ui/button";
import { Badge, Field, Notice, PageHeader, Row, Rows, Section, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { has } from "@/lib/v2/access";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText, rowsOf } from "@/lib/v2/api";
import {
  displayName,
  GRANT_DURATIONS,
  grantState,
  requestable,
  scopesFor,
  type CatalogRow,
  type Grant,
  type Member,
} from "@/lib/v2/screens/people";
import { useOrgData } from "@/lib/v2/useOrgData";

type Req = {
  id: string;
  perm_key: string;
  label: string;
  scope_type: string;
  scope_name: string | null;
  reason: string;
  status: "pending" | "approved" | "rejected";
  created_at: string;
  decided_at: string | null;
  requester_user: { id: string; username: string } | null;
  decided_by_user: { id: string; username: string } | null;
};
type Named = { id: string; name: string };
type Msg = { kind: "ok" | "error"; text: string } | null;

const SCOPE_LABEL: Record<string, string> = { org: "Whole organization", team: "One team", project: "One project" };

/**
 * Access for everyone: ask for a permission and see what you hold (Decision 29). People who decide
 * requests see the queue; people who grant see the grant form and every grant.
 */
export function AccessScreen({ orgSlug }: { orgSlug: string }) {
  const tr = useTr();
  const { orgId, access } = useAccess();
  const canDecide = has(access, "permission_requests.decide");
  const canGrant = has(access, "grants.create");
  const canRevoke = has(access, "grants.revoke");
  const catalog = useOrgData<CatalogRow[]>(orgId, "/permissions");
  const teams = useOrgData<(Named & { is_active: boolean })[]>(orgId, "/teams?scope=all");
  const projects = useOrgData<(Named & { status: string })[]>(orgId, "/projects");
  const mine = useOrgData<{ results: Req[] }>(orgId, "/permission-requests?mine=1");
  const queue = useOrgData<{ results: Req[] }>(orgId, canDecide ? "/permission-requests?status=pending&page_size=100" : null);
  const myGrants = useOrgData<{ results: Grant[] }>(orgId, access ? `/grants?grantee=${access.user_id}&page_size=100` : null);
  const allGrants = useOrgData<{ results: Grant[] }>(orgId, canGrant || canRevoke ? "/grants?page_size=100" : null);
  const [message, setMessage] = useState<Msg>(null);
  const scopes = { teams: (teams.data ?? []).filter((t) => t.is_active), projects: (projects.data ?? []).filter((p) => p.status !== "archived") };

  const refresh = () => {
    mine.reload();
    if (canDecide) queue.reload();
    myGrants.reload();
    if (canGrant || canRevoke) allGrants.reload();
  };

  async function decide(row: Req, decision: "approve" | "reject", days: number | null) {
    setMessage(null);
    try {
      await api.post(`/orgs/${orgId}/permission-requests/${row.id}/${decision}`, decision === "approve" && days ? { expires_in_days: days } : {});
      setMessage({ kind: "ok", text: decision === "approve" ? tr("Approved. They have it now.") : tr("Rejected. They were told.") });
      refresh();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  async function revoke(id: string) {
    setMessage(null);
    try {
      await api.del(`/orgs/${orgId}/grants/${id}`);
      setMessage({ kind: "ok", text: tr("Grant revoked.") });
      refresh();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  return (
    <div className="max-w-5xl">
      <PageHeader
        title={tr("Access")}
        intro={tr("What you can do here comes from your role. If you need more, ask for it: someone who holds that permission decides.")}
        action={
          has(access, "audit.view") ? (
            <Button asChild variant="outline">
              <Link href={`/w/${orgSlug}/settings/audit`}>{tr("Audit log")}</Link>
            </Button>
          ) : undefined
        }
      />
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}

      {canDecide ? (
        <Section title={tr("Requests waiting for a decision")} aside={queue.data?.results.length ? <Badge tone="waiting">{queue.data.results.length}</Badge> : undefined}>
          <ScreenBody state={queue.state} error={queue.error} emptyLabel={tr("No requests are waiting.")} onRetry={queue.reload}>
            <Rows>
              {(queue.data?.results ?? [])
                .filter((r) => r.requester_user?.id !== access?.user_id)
                .map((r) => (
                  <DecideRow key={r.id} row={r} onDecide={decide} />
                ))}
            </Rows>
          </ScreenBody>
        </Section>
      ) : null}

      {canGrant && orgId ? (
        <GrantForm
          orgId={orgId}
          catalog={(catalog.data ?? []).filter((c) => c.grantable !== false && access?.permissions.includes(c.key))}
          scopes={scopes}
          onDone={(text) => {
            setMessage({ kind: "ok", text });
            refresh();
          }}
        />
      ) : null}

      {has(access, "permission_requests.create") && orgId ? (
        <RequestForm
          orgId={orgId}
          catalog={requestable(catalog.data ?? [], access?.permissions ?? [])}
          scopes={scopes}
          onDone={(text) => {
            setMessage({ kind: "ok", text });
            refresh();
          }}
        />
      ) : null}

      <div className="grid gap-x-8 md:grid-cols-2">
        <Section title={tr("Your requests")}>
          <ScreenBody state={mine.state} error={mine.error} emptyLabel={tr("You haven't asked for anything yet.")} onRetry={mine.reload}>
            <Rows>
              {(mine.data?.results ?? []).map((r) => (
                <Row key={r.id}>
                  <div className="min-w-0">
                    <p className="font-medium">{r.label}</p>
                    <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
                      {r.scope_name ?? tr(SCOPE_LABEL[r.scope_type] ?? r.scope_type)} · {when(r.created_at)}
                    </p>
                  </div>
                  <Badge tone={r.status === "approved" ? "good" : r.status === "rejected" ? "bad" : "waiting"}>{tr(`request|${r.status}`)}</Badge>
                </Row>
              ))}
            </Rows>
          </ScreenBody>
        </Section>
        <Section title={tr("Extra access you hold")}>
          <ScreenBody state={myGrants.state} error={myGrants.error} emptyLabel={tr("Only what your role gives you.")} onRetry={myGrants.reload}>
            <GrantList rows={myGrants.data?.results ?? []} />
          </ScreenBody>
        </Section>
      </div>

      {canGrant || canRevoke ? (
        <Section title={tr("All grants")}>
          <ScreenBody state={allGrants.state} error={allGrants.error} emptyLabel={tr("Nobody has extra access yet.")} onRetry={allGrants.reload}>
            <GrantList rows={allGrants.data?.results ?? []} showGrantee onRevoke={canRevoke ? revoke : undefined} />
          </ScreenBody>
        </Section>
      ) : null}
    </div>
  );
}

function DecideRow({ row, onDecide }: { row: Req; onDecide: (row: Req, d: "approve" | "reject", days: number | null) => Promise<void> }) {
  const tr = useTr();
  const [days, setDays] = useState<string>("");
  return (
    <Row className="items-start">
      <div className="min-w-0 max-w-md">
        <p className="font-medium">
          {tr("{name} asks for: {permission}", { name: row.requester_user?.username ?? "", permission: row.label })}
        </p>
        <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
          {row.scope_name ?? tr(SCOPE_LABEL[row.scope_type] ?? row.scope_type)} · {when(row.created_at)}
        </p>
        {row.reason ? <p className="mt-1 text-sm">“{row.reason}”</p> : null}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <label className="text-sm">
          <span className="sr-only">{tr("How long")}</span>
          <select className="v2-input w-44" value={days} onChange={(e) => setDays(e.target.value)}>
            {GRANT_DURATIONS.map((d) => (
              <option key={d.label} value={d.days ?? ""}>
                {tr(d.label)}
              </option>
            ))}
          </select>
        </label>
        <Button variant="waiting" onClick={() => onDecide(row, "approve", days ? Number(days) : null)}>
          {tr("Approve")}
        </Button>
        <Button variant="ghost" onClick={() => onDecide(row, "reject", null)}>
          {tr("Reject")}
        </Button>
      </div>
    </Row>
  );
}

function ScopePicker({
  catalogRow,
  scopes,
  scope,
  setScope,
  target,
  setTarget,
}: {
  catalogRow: CatalogRow | undefined;
  scopes: { teams: Named[]; projects: Named[] };
  scope: string;
  setScope: (v: string) => void;
  target: string;
  setTarget: (v: string) => void;
}) {
  const tr = useTr();
  const options = scopesFor(catalogRow);
  if (options.length === 1) return null;
  const list = scope === "team" ? scopes.teams : scope === "project" ? scopes.projects : [];
  return (
    <>
      <Field label={tr("Where")}>
        <select
          className="v2-input"
          value={scope}
          onChange={(e) => {
            setScope(e.target.value);
            setTarget("");
          }}
        >
          {options.map((o) => (
            <option key={o} value={o}>
              {tr(SCOPE_LABEL[o])}
            </option>
          ))}
        </select>
      </Field>
      {scope !== "org" ? (
        <Field label={scope === "team" ? tr("Team") : tr("Project")}>
          <select className="v2-input" value={target} onChange={(e) => setTarget(e.target.value)} required>
            <option value="">{tr("Pick one")}</option>
            {list.map((x) => (
              <option key={x.id} value={x.id}>
                {x.name}
              </option>
            ))}
          </select>
        </Field>
      ) : null}
    </>
  );
}

function RequestForm({ orgId, catalog, scopes, onDone }: { orgId: string; catalog: CatalogRow[]; scopes: { teams: Named[]; projects: Named[] }; onDone: (t: string) => void }) {
  const tr = useTr();
  const [key, setKey] = useState("");
  const [scope, setScope] = useState("org");
  const [target, setTarget] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const row = catalog.find((c) => c.key === key);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await api.post(`/orgs/${orgId}/permission-requests`, { perm_key: key, scope_type: scope, ...(scope !== "org" ? { scope_id: target } : {}), reason });
      setKey("");
      setReason("");
      setScope("org");
      onDone(tr("Request sent. You'll get a notification when someone decides."));
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <Section title={tr("Ask for access")}>
      <form onSubmit={submit} className="grid gap-x-4 rounded-xl bg-[color:var(--fb-v2-surface)] p-4 md:grid-cols-2">
        <Field label={tr("Permission")}>
          <select
            className="v2-input"
            value={key}
            onChange={(e) => {
              setKey(e.target.value);
              setScope("org");
            }}
            required
          >
            <option value="">{tr("Pick a permission")}</option>
            {catalog.map((c) => (
              <option key={c.key} value={c.key}>
                {c.label}
              </option>
            ))}
          </select>
        </Field>
        <ScopePicker catalogRow={row} scopes={scopes} scope={scope} setScope={setScope} target={target} setTarget={setTarget} />
        <div className="md:col-span-2">
          <Field label={tr("Why you need it")} hint={tr("A sentence helps the person who decides.")}>
            <textarea className="v2-input" rows={2} maxLength={1000} value={reason} onChange={(e) => setReason(e.target.value)} />
          </Field>
          <Button type="submit" disabled={!key}>
            {tr("Send request")}
          </Button>
          {error ? <Notice kind="error">{error}</Notice> : null}
        </div>
      </form>
    </Section>
  );
}

function GrantForm({ orgId, catalog, scopes, onDone }: { orgId: string; catalog: CatalogRow[]; scopes: { teams: Named[]; projects: Named[] }; onDone: (t: string) => void }) {
  const tr = useTr();
  const { access } = useAccess();
  const people = useOrgData<{ results: Member[] }>(orgId, "/members?status=active&page_size=100");
  const [grantee, setGrantee] = useState("");
  const [key, setKey] = useState("");
  const [scope, setScope] = useState("org");
  const [target, setTarget] = useState("");
  const [days, setDays] = useState("7");
  const [error, setError] = useState("");
  const row = catalog.find((c) => c.key === key);
  const sorted = useMemo(() => [...catalog].sort((a, b) => a.label.localeCompare(b.label)), [catalog]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await api.post(`/orgs/${orgId}/grants`, {
        grantee,
        perm_key: key,
        scope_type: scope,
        ...(scope !== "org" ? { scope_id: target } : {}),
        ...(days ? { expires_in_days: Number(days) } : {}),
      });
      setKey("");
      onDone(tr("Granted. They were notified."));
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <Section title={tr("Give someone access")}>
      <form onSubmit={submit} className="grid gap-x-4 rounded-xl bg-[color:var(--fb-v2-surface)] p-4 md:grid-cols-2">
        <Field label={tr("Person")}>
          <select className="v2-input" value={grantee} onChange={(e) => setGrantee(e.target.value)} required>
            <option value="">{tr("Pick a person")}</option>
            {rowsOf<Member>(people.data)
              .filter((m) => m.id !== access?.user_id && m.org_role === "member")
              .map((m) => (
                <option key={m.id} value={m.id}>
                  {displayName(m)}
                </option>
              ))}
          </select>
        </Field>
        <Field label={tr("Permission")} hint={tr("You can only give what you hold yourself.")}>
          <select
            className="v2-input"
            value={key}
            onChange={(e) => {
              setKey(e.target.value);
              setScope("org");
            }}
            required
          >
            <option value="">{tr("Pick a permission")}</option>
            {sorted.map((c) => (
              <option key={c.key} value={c.key}>
                {c.label}
              </option>
            ))}
          </select>
        </Field>
        <ScopePicker catalogRow={row} scopes={scopes} scope={scope} setScope={setScope} target={target} setTarget={setTarget} />
        <Field label={tr("How long")}>
          <select className="v2-input" value={days} onChange={(e) => setDays(e.target.value)}>
            {GRANT_DURATIONS.map((d) => (
              <option key={d.label} value={d.days ?? ""}>
                {tr(d.label)}
              </option>
            ))}
          </select>
        </Field>
        <div className="md:col-span-2">
          <Button type="submit" disabled={!grantee || !key}>
            {tr("Grant")}
          </Button>
          {error ? <Notice kind="error">{error}</Notice> : null}
        </div>
      </form>
    </Section>
  );
}

function GrantList({ rows, showGrantee = false, onRevoke }: { rows: Grant[]; showGrantee?: boolean; onRevoke?: (id: string) => Promise<void> }) {
  const tr = useTr();
  const tone = { active: "good", expiring: "waiting", expired: "neutral", revoked: "neutral" } as const;
  const label = { active: "Active", expiring: "Ends soon", expired: "Expired", revoked: "Revoked" } as const;
  return (
    <Rows>
      {rows.map((g) => {
        const state = grantState(g);
        return (
          <Row key={g.id} className="items-start">
            <div className="min-w-0">
              <p className="font-medium">
                {showGrantee ? `${g.grantee_user?.username ?? ""}: ` : ""}
                {g.label ?? g.perm_key}
              </p>
              <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
                {g.scope_name ?? tr(SCOPE_LABEL[g.scope_type] ?? g.scope_type)}
                {g.granted_by_user ? ` · ${tr("from {name}", { name: g.granted_by_user.username })}` : ""}
                {g.expires_at ? ` · ${tr("until {date}", { date: when(g.expires_at) })}` : ` · ${tr("no end date")}`}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <Badge tone={tone[state]}>{tr(label[state])}</Badge>
              {onRevoke && (state === "active" || state === "expiring") ? (
                <ConfirmButton
                  label={tr("Revoke")}
                  variant="danger"
                  question={tr("Revoke this access now? It stops working right away.")}
                  onConfirm={() => onRevoke(g.id)}
                />
              ) : null}
            </div>
          </Row>
        );
      })}
    </Rows>
  );
}
