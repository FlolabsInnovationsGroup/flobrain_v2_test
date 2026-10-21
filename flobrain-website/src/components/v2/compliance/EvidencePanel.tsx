"use client";

import { useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Badge, Field, Notice, Section, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { apiClient } from "@/lib/axios";
import { api, errorText } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

import { inputClass } from "./bits";
import { formatBytes, isoDaysAgo, shortHash } from "./logic";
import type { EvidencePackage } from "./types";

function PackageStatus({ p }: { p: EvidencePackage }) {
  const tr = useTr();
  if (p.status === "ready") return <Badge tone="good">{tr("Ready")}</Badge>;
  if (p.status === "failed") return <Badge tone="bad">{tr("Failed")}</Badge>;
  if (p.status === "expired") return <Badge>{tr("Expired")}</Badge>;
  return <Badge>{tr("Building")}</Badge>;
}

export function EvidencePanel({ orgId, canManage }: { orgId: string; canManage: boolean }) {
  const tr = useTr();
  const list = useOrgData<EvidencePackage[]>(orgId, "/compliance/evidence");
  const [start, setStart] = useState(isoDaysAgo(90));
  const [end, setEnd] = useState(isoDaysAgo(0));
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const packages = list.data ?? [];

  async function build() {
    setBusy(true);
    setMessage(null);
    try {
      await api.post(`/orgs/${orgId}/compliance/evidence`, { start, end });
      setMessage({ kind: "ok", text: tr("Package ready. It can be downloaded for 7 days.") });
      list.reload();
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    } finally {
      setBusy(false);
    }
  }

  async function download(p: EvidencePackage) {
    setMessage(null);
    try {
      const res = await apiClient.get<Blob>(`/api/v2/orgs/${orgId}/compliance/evidence/${p.id}/download`, { responseType: "blob" });
      const url = URL.createObjectURL(res.data);
      const link = document.createElement("a");
      link.href = url;
      link.download = `evidence-${p.period_end.slice(0, 10)}.zip`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  return (
    <>
      {canManage ? (
        <form
          className="mb-6 rounded-xl bg-[color:var(--fb-v2-surface)] p-4"
          onSubmit={(e) => {
            e.preventDefault();
            build();
          }}
        >
          <p className="mb-3 text-sm text-[color:var(--fb-v2-text-muted)]">
            {tr("One ZIP for your auditor: control status, the audit log for the period, access review results, policy acknowledgements and a settings snapshot without secrets. A manifest lists the SHA-256 of every file.")}
          </p>
          <div className="grid gap-x-4 sm:grid-cols-3 sm:items-end">
            <Field label={tr("From")}>
              <input className={inputClass} type="date" value={start} max={end} onChange={(e) => setStart(e.target.value)} />
            </Field>
            <Field label={tr("To")}>
              <input className={inputClass} type="date" value={end} min={start} onChange={(e) => setEnd(e.target.value)} />
            </Field>
            <div className="mb-4">
              <Button type="submit" disabled={busy}>
                {busy ? tr("Building…") : tr("Build package")}
              </Button>
            </div>
          </div>
        </form>
      ) : null}
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      <Section title={tr("Evidence packages")}>
        <ScreenBody state={list.state === "ready" && !packages.length ? "empty" : list.state} error={list.error} emptyLabel={tr("No packages yet.")} onRetry={list.reload}>
          <ul className="divide-y divide-[color:var(--fb-v2-border)] rounded-xl bg-[color:var(--fb-v2-surface)]">
            {packages.map((p) => (
              <li key={p.id} className="px-4 py-3">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="min-w-0 flex-1 basis-64">
                    <p className="font-medium">
                      {tr("{start} to {end}", { start: p.period_start.slice(0, 10), end: p.period_end.slice(0, 10) })}
                    </p>
                    <p className="text-xs text-[color:var(--fb-v2-text-muted)]">
                      {tr("Made {when}", { when: when(p.created_at) })}
                      {p.created_by ? ` · ${tr("by {name}", { name: p.created_by })}` : ""}
                      {p.status === "ready" && p.expires_at ? ` · ${tr("Expires {when}", { when: when(p.expires_at) })}` : ""}
                      {p.size_bytes ? ` · ${formatBytes(p.size_bytes)}` : ""}
                    </p>
                    {p.sha256 ? (
                      <p className="v2-mono text-xs text-[color:var(--fb-v2-text-faint)]" dir="ltr" title={p.sha256}>
                        SHA-256 {shortHash(p.sha256)}
                      </p>
                    ) : null}
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <PackageStatus p={p} />
                    {p.files.length ? (
                      <Button variant="ghost" aria-expanded={open === p.id} onClick={() => setOpen(open === p.id ? null : p.id)}>
                        {tr("Files")}
                      </Button>
                    ) : null}
                    {canManage && p.status === "ready" ? (
                      <Button variant="outline" onClick={() => download(p)}>
                        {tr("Download")}
                      </Button>
                    ) : null}
                  </div>
                </div>
                {open === p.id ? (
                  <div className="mt-3 overflow-x-auto">
                    <table className="w-full min-w-[30rem] text-xs">
                      <thead className="text-[color:var(--fb-v2-text-muted)]">
                        <tr>
                          <th className="py-1 text-start font-medium">{tr("File")}</th>
                          <th className="py-1 text-end font-medium">{tr("Size")}</th>
                          <th className="py-1 text-start font-medium ps-4">SHA-256</th>
                        </tr>
                      </thead>
                      <tbody className="v2-mono" dir="ltr">
                        {p.files.map((f) => (
                          <tr key={f.path}>
                            <td className="py-0.5">{f.path}</td>
                            <td className="py-0.5 text-end">{formatBytes(f.bytes)}</td>
                            <td className="py-0.5 ps-4 break-all">{f.sha256}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        </ScreenBody>
      </Section>
    </>
  );
}
