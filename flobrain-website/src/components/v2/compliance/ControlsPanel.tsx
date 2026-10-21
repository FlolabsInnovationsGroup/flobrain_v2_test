"use client";

import { useMemo, useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Field, Notice, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, errorText } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

import { StatusBadge, inputClass } from "./bits";
import { checkTitle } from "./checkTitles";
import { filterControls, groupsOf, type ControlFilter } from "./logic";
import type { CheckResult, Control } from "./types";

type Member = { id?: string; user_id?: string; username?: string; name?: string; email?: string };

function AttestForm({ orgId, control, members, onSaved }: { orgId: string; control: Control; members: Member[]; onSaved: (c: Control) => void }) {
  const tr = useTr();
  const [status, setStatus] = useState<"pass" | "fail" | "not_applicable">(control.attestation?.status ?? "pass");
  const [note, setNote] = useState(control.attestation?.note ?? "");
  const [url, setUrl] = useState(control.attestation?.evidence_url ?? "");
  const [owner, setOwner] = useState(control.attestation?.owner?.id ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const path = `/orgs/${orgId}/compliance/controls/${control.framework}/${encodeURIComponent(control.id)}/attestation`;
  const idp = `att-${control.framework}-${control.id}`;

  async function save() {
    setBusy(true);
    setError(null);
    try {
      onSaved(await api.put<Control>(path, { status, note, evidence_url: url, owner: owner || null }));
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    try {
      await api.del(path);
      onSaved({ ...control, attestation: null });
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      className="mt-3 rounded-lg bg-[color:var(--fb-v2-raised)] p-3"
      onSubmit={(e) => {
        e.preventDefault();
        save();
      }}
    >
      <fieldset className="mb-3">
        <legend className="mb-1 text-sm font-medium">{tr("Your statement")}</legend>
        <div className="flex flex-wrap gap-3 text-sm">
          <label className="flex items-center gap-1.5">
            <input type="radio" name={`${idp}-status`} checked={status === "pass"} onChange={() => setStatus("pass")} />
            {tr("We have evidence")}
          </label>
          <label className="flex items-center gap-1.5">
            <input type="radio" name={`${idp}-status`} checked={status === "fail"} onChange={() => setStatus("fail")} />
            {tr("Known gap")}
          </label>
          <label className="flex items-center gap-1.5">
            <input type="radio" name={`${idp}-status`} checked={status === "not_applicable"} onChange={() => setStatus("not_applicable")} />
            {tr("Does not apply")}
          </label>
        </div>
      </fieldset>
      <Field label={tr("What is the evidence, or why does it not apply?")}>
        <textarea className={`${inputClass} min-h-20`} dir="auto" maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} />
      </Field>
      <div className="grid gap-x-4 sm:grid-cols-2">
        <Field label={tr("Link to the evidence (optional)")} hint={tr("An https link or a path inside FloBrain.")}>
          <input className={inputClass} dir="ltr" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://" />
        </Field>
        <Field label={tr("Control owner (optional)")}>
          <select className={inputClass} value={owner} onChange={(e) => setOwner(e.target.value)}>
            <option value="">{tr("Nobody yet")}</option>
            {members.map((m) => {
              const id = m.user_id ?? m.id ?? "";
              return (
                <option key={id} value={id}>
                  {m.name ?? m.username ?? m.email}
                </option>
              );
            })}
          </select>
        </Field>
      </div>
      {error ? <Notice kind="error">{error}</Notice> : null}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={busy}>
          {tr("Save statement")}
        </Button>
        {control.attestation ? (
          <Button type="button" variant="ghost" disabled={busy} onClick={remove}>
            {tr("Remove statement")}
          </Button>
        ) : null}
      </div>
      <p className="mt-2 text-xs text-[color:var(--fb-v2-text-muted)]">{tr("A statement can't turn a failing automated check into a pass. Fix the setting instead.")}</p>
    </form>
  );
}

function ControlRow({ control, checks, orgId, canManage, members, onSaved }: { control: Control; checks: Record<string, CheckResult>; orgId: string; canManage: boolean; members: Member[]; onSaved: (c: Control) => void }) {
  const tr = useTr();
  const [open, setOpen] = useState(false);
  const panel = `ctl-${control.framework}-${control.id}`;
  const source =
    control.source === "automated" ? tr("From automated checks") : control.source === "attested" ? tr("From a statement") : tr("No evidence yet");
  return (
    <li className="px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <button type="button" aria-expanded={open} aria-controls={panel} onClick={() => setOpen((v) => !v)} className="flex min-w-0 flex-1 basis-64 items-baseline gap-3 text-start">
          <span className="v2-mono w-14 shrink-0 text-xs text-[color:var(--fb-v2-text-muted)]">{control.id}</span>
          <span className="min-w-0">
            <span className="block font-medium" dir="ltr">
              {control.name}
            </span>
            <span className="block text-xs text-[color:var(--fb-v2-text-muted)]">
              {control.group_name} · {source}
            </span>
          </span>
        </button>
        <StatusBadge status={control.status} />
      </div>
      {open ? (
        <div id={panel} className="mt-3 ps-0 sm:ps-[4.25rem]">
          <p className="text-sm" dir="ltr">
            {control.summary}
          </p>
          {control.check_results.length ? (
            <ul className="mt-3 space-y-2">
              {control.check_results.map((c) => (
                <li key={c.key} className="rounded-lg bg-[color:var(--fb-v2-raised)] px-3 py-2 text-sm">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-medium">{checkTitle(tr, c.key, c.title)}</span>
                    <StatusBadge status={c.status} />
                  </div>
                  {checks[c.key] ? (
                    <p className="mt-1 text-xs text-[color:var(--fb-v2-text-muted)]" dir="auto">
                      {checks[c.key].summary}
                    </p>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-sm text-[color:var(--fb-v2-text-muted)]">{tr("FloBrain can't check this one. Attach evidence from outside FloBrain.")}</p>
          )}
          {control.attestation ? (
            <div className="mt-3 text-sm">
              <p className="text-[color:var(--fb-v2-text-muted)]">
                {tr("Statement by {who}, {when}", { who: control.attestation.by, when: when(control.attestation.at) })}
                {control.attestation.owner ? ` · ${tr("Owner: {name}", { name: control.attestation.owner.name })}` : ""}
              </p>
              <p dir="auto">{control.attestation.note}</p>
              {control.attestation.evidence_url ? (
                <a className="text-[color:var(--fb-v2-accent)] underline underline-offset-2" href={control.attestation.evidence_url} target="_blank" rel="noopener noreferrer" dir="ltr">
                  {control.attestation.evidence_url}
                </a>
              ) : null}
            </div>
          ) : null}
          {canManage ? <AttestForm orgId={orgId} control={control} members={members} onSaved={onSaved} /> : null}
        </div>
      ) : null}
    </li>
  );
}

export function ControlsPanel({ orgId, canManage }: { orgId: string; canManage: boolean }) {
  const tr = useTr();
  const { data, state, error, reload, setData } = useOrgData<{ controls: Control[]; checks: Record<string, CheckResult> }>(orgId, "/compliance/controls");
  const { data: membersRaw } = useOrgData<{ results?: Member[] } | Member[]>(orgId, canManage ? "/members?status=active&page_size=200" : null);
  const members = Array.isArray(membersRaw) ? membersRaw : (membersRaw?.results ?? []);
  const [filter, setFilter] = useState<ControlFilter>({ framework: "", status: "", group: "", q: "" });
  const controls = useMemo(() => data?.controls ?? [], [data]);
  const shown = useMemo(() => filterControls(controls, filter), [controls, filter]);
  const groups = useMemo(() => groupsOf(controls, filter.framework), [controls, filter.framework]);
  const frameworks = useMemo(() => [...new Set(controls.map((c) => c.framework))], [controls]);

  function saved(next: Control) {
    setData((prev) => (prev ? { ...prev, controls: prev.controls.map((c) => (c.framework === next.framework && c.id === next.id ? { ...c, ...next } : c)) } : prev));
  }

  return (
    <ScreenBody state={state} error={error} onRetry={reload}>
      <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label className="text-sm">
          <span className="mb-1 block text-[color:var(--fb-v2-text-muted)]">{tr("Framework")}</span>
          <select className={inputClass} value={filter.framework} onChange={(e) => setFilter({ ...filter, framework: e.target.value, group: "" })}>
            <option value="">{tr("All frameworks")}</option>
            {frameworks.includes("soc2") ? <option value="soc2">SOC 2</option> : null}
            {frameworks.includes("iso27001") ? <option value="iso27001">ISO/IEC 27001:2022</option> : null}
          </select>
        </label>
        <label className="text-sm">
          <span className="mb-1 block text-[color:var(--fb-v2-text-muted)]">{tr("Status")}</span>
          <select className={inputClass} value={filter.status} onChange={(e) => setFilter({ ...filter, status: e.target.value })}>
            <option value="">{tr("Any status")}</option>
            <option value="pass">{tr("Passing")}</option>
            <option value="fail">{tr("Gap")}</option>
            <option value="manual">{tr("Needs evidence")}</option>
            <option value="not_applicable">{tr("Not applicable")}</option>
          </select>
        </label>
        <label className="text-sm">
          <span className="mb-1 block text-[color:var(--fb-v2-text-muted)]">{tr("Area")}</span>
          <select className={inputClass} value={filter.group} onChange={(e) => setFilter({ ...filter, group: e.target.value })}>
            <option value="">{tr("All areas")}</option>
            {groups.map((g) => (
              <option key={g.key} value={g.key}>
                {g.key} · {g.name}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          <span className="mb-1 block text-[color:var(--fb-v2-text-muted)]">{tr("Search")}</span>
          <input className={inputClass} type="search" value={filter.q} onChange={(e) => setFilter({ ...filter, q: e.target.value })} placeholder={tr("Number or name")} />
        </label>
      </div>
      <p className="mb-2 text-sm text-[color:var(--fb-v2-text-muted)]" aria-live="polite">
        {tr("{n} of {total} controls", { n: shown.length, total: controls.length })}
      </p>
      {shown.length ? (
        <ul className="divide-y divide-[color:var(--fb-v2-border)] rounded-xl bg-[color:var(--fb-v2-surface)]">
          {shown.map((c) => (
            <ControlRow key={`${c.framework}-${c.id}`} control={c} checks={data?.checks ?? {}} orgId={orgId} canManage={canManage} members={members} onSaved={saved} />
          ))}
        </ul>
      ) : (
        <p className="p-6 text-[color:var(--fb-v2-text-muted)]">{tr("No control matches these filters.")}</p>
      )}
      <p className="mt-4 text-xs text-[color:var(--fb-v2-text-muted)]">
        {tr("Control numbers and short names follow the AICPA Trust Services Criteria and ISO/IEC 27001:2022 Annex A. Descriptions are our own short summaries, not the official text.")}
      </p>
    </ScreenBody>
  );
}
