"use client";

import { useState } from "react";

import { Badge, Notice, Row, Rows, Section } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, errorText } from "@/lib/v2/api";

import type { Residency, ResidencyRow } from "./types";

const select =
  "rounded-lg bg-[color:var(--fb-v2-raised)] px-3 py-2 text-sm ring-1 ring-inset ring-[color:var(--fb-v2-border)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[color:var(--fb-v2-accent)]";

export function ResidencyPanel({ orgId, data, onChange }: { orgId: string; data: Residency; onChange: (r: Residency) => void }) {
  const tr = useTr();
  const [msg, setMsg] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  const regionName = (code: string) =>
    code === "sa" ? tr("Saudi Arabia") : code === "ae" ? tr("United Arab Emirates") : code === "eg" ? tr("Egypt") : code === "eu" ? tr("European Union") : code === "us" ? tr("United States") : code === "unknown" || !code ? tr("Unknown") : code.toUpperCase();
  const className = (c: string) =>
    c === "database" ? tr("Database and backups") : c === "files" ? tr("Files and recordings") : c === "ai" ? tr("AI model") : c === "legacy_ai" ? tr("Legacy AI service") : c === "embeddings" ? tr("Search index") : tr("Transcription");
  const tone = (row: ResidencyRow) => (row.status === "ok" ? "good" : row.status === "mismatch" || row.status === "blocked" ? "bad" : "neutral");
  const statusText = (row: ResidencyRow) =>
    row.status === "ok" ? tr("In region") : row.status === "mismatch" ? tr("Outside the region") : row.status === "blocked" ? tr("Outside, AI calls refused") : row.status === "not_configured" ? tr("Not set up") : tr("Location not known");

  async function save(body: Record<string, unknown>) {
    setMsg(null);
    try {
      onChange(await api.patch<Residency>(`/orgs/${orgId}/einvoice/residency`, body));
      setMsg({ kind: "ok", text: tr("Saved.") });
    } catch (err) {
      setMsg({ kind: "error", text: errorText(err) });
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <Section title={tr("Data region")}>
        <p className="mb-3 text-sm text-[color:var(--fb-v2-text-muted)]">
          {tr("Choose where your organization's data should stay. Pinning the region stops AI requests to services outside it. Where each kind of data lives comes from the server's settings.")}
        </p>
        <div className="flex flex-wrap items-center gap-4">
          <label className="flex items-center gap-2 text-sm">
            <span className="font-medium">{tr("Region")}</span>
            <select className={select} value={data.region} disabled={!data.can_change} onChange={(e) => save({ region: e.target.value })}>
              <option value="">{tr("Not chosen")}</option>
              {data.regions.map((r) => (
                <option key={r.code} value={r.code}>{regionName(r.code)}</option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={data.pinned} disabled={!data.can_change || !data.region} onChange={(e) => save({ pinned: e.target.checked })} />
            <span>{tr("Pin it: refuse AI services outside this region")}</span>
          </label>
        </div>
        {!data.can_change ? <Notice>{tr("Only an owner or admin who manages e-invoicing can change this.")}</Notice> : null}
        {msg ? <Notice kind={msg.kind}>{msg.text}</Notice> : null}
      </Section>
      <Section title={tr("Where your data lives")} aside={<span className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("This server runs in: {region}", { region: regionName(data.deployment_region) })}</span>}>
        {data.mismatches.length ? <Notice kind="error">{tr("{n} kinds of data are outside your region.", { n: data.mismatches.length })}</Notice> : null}
        <Rows>
          {data.classes.map((row) => (
            <Row key={row.class}>
              <div className="min-w-0 flex-1 basis-56">
                <p className="font-medium">{className(row.class)}</p>
                <p className="text-xs text-[color:var(--fb-v2-text-muted)]">
                  <span dir="ltr">{row.where || tr("Not set up")}</span> · {regionName(row.region)}
                </p>
              </div>
              <Badge tone={tone(row)}>{statusText(row)}</Badge>
            </Row>
          ))}
        </Rows>
      </Section>
    </div>
  );
}
