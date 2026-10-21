"use client";

import { useRef, useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Field, Notice } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, apiClientUpload, errorText } from "@/lib/v2/api";

import type { Dataset, Meta } from "./types";

type Kind = "upload" | "sheet" | "postgres";
type Team = { id: string; name: string };

/** True for the files the upload accepts; checked again on the server. */
export function acceptedFile(name: string): boolean {
  return /\.(csv|tsv|txt|xlsx)$/i.test(name);
}

function Sharing({ value, team, teams, onChange }: { value: string; team: string; teams: Team[]; onChange: (v: string, t: string) => void }) {
  const tr = useTr();
  return (
    <fieldset className="mb-4 text-sm">
      <legend className="mb-1 font-medium">{tr("Who can see it")}</legend>
      <div className="flex flex-wrap gap-3">
        {(["org", "team", "owner"] as const).map((v) => (
          <label key={v} className="flex items-center gap-1.5">
            <input type="radio" name="visibility" value={v} checked={value === v} onChange={() => onChange(v, team || teams[0]?.id || "")} />
            {tr({ org: "Everyone in the organization", team: "One team", owner: "Only me" }[v])}
          </label>
        ))}
      </div>
      {value === "team" ? (
        <select className="v2-input mt-2 w-full sm:w-64" aria-label={tr("Team")} value={team} onChange={(e) => onChange(value, e.target.value)}>
          {teams.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </select>
      ) : null}
    </fieldset>
  );
}

export function AddSource({ orgId, meta, teams, onAdded }: { orgId: string; meta: Meta | null; teams: Team[]; onAdded: (d: Dataset) => void }) {
  const tr = useTr();
  const [kind, setKind] = useState<Kind>("upload");
  const [name, setName] = useState("");
  const [visibility, setVisibility] = useState("org");
  const [team, setTeam] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [url, setUrl] = useState("");
  const [hours, setHours] = useState("24");
  const [dsn, setDsn] = useState("");
  const [tables, setTables] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const maxMb = meta?.max_upload_mb ?? 10;

  function pick(f: File | null | undefined) {
    setError("");
    if (!f) return;
    if (!acceptedFile(f.name)) return setError(tr("Upload a .csv or .xlsx file."));
    if (f.size > maxMb * 1024 * 1024) return setError(tr("Files can be at most {n} MB.", { n: maxMb }));
    setFile(f);
    if (!name) setName(f.name.replace(/\.[^.]+$/, ""));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    const common = { name, visibility, ...(visibility === "team" ? { team } : {}) };
    try {
      let made: Dataset;
      if (kind === "upload") {
        if (!file) throw new Error(tr("Pick a file first."));
        const body = new FormData();
        body.append("file", file);
        Object.entries(common).forEach(([k, v]) => body.append(k, v));
        made = await apiClientUpload<Dataset>(`/orgs/${orgId}/data/datasets/upload`, body);
      } else if (kind === "sheet") {
        made = await api.post<Dataset>(`/orgs/${orgId}/data/datasets/sheet`, { ...common, url, refresh_every_hours: Number(hours) });
      } else {
        const wanted = tables.split(",").map((t) => t.trim()).filter(Boolean);
        made = await api.post<Dataset>(`/orgs/${orgId}/data/datasets/postgres`, { ...common, dsn, ...(wanted.length ? { tables: wanted } : {}) });
      }
      setDsn(""); // never keep the password in the page longer than needed
      setFile(null);
      setUrl("");
      setName("");
      onAdded(made);
    } catch (err) {
      setError(err instanceof Error && !("response" in err) ? err.message : errorText(err));
    } finally {
      setBusy(false);
    }
  }

  const tabs: { key: Kind; label: string }[] = [
    { key: "upload", label: tr("Upload a file") },
    { key: "sheet", label: tr("Google Sheet") },
    { key: "postgres", label: tr("PostgreSQL") },
  ];

  return (
    <form onSubmit={submit} className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
      <div role="tablist" aria-label={tr("Source type")} className="mb-4 flex flex-wrap gap-2">
        {tabs.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={kind === t.key}
            onClick={() => {
              setKind(t.key);
              setError("");
            }}
            className={`rounded-full px-3 py-1 text-sm ${kind === t.key ? "bg-[color:var(--fb-v2-accent)] text-white" : "ring-1 ring-inset ring-[color:var(--fb-v2-border)]"}`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {kind === "upload" ? (
        <div
          role="button"
          tabIndex={0}
          aria-label={tr("Choose a file or drop it here")}
          onClick={() => input.current?.click()}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              input.current?.click();
            }
          }}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            pick(e.dataTransfer.files?.[0]);
          }}
          className={`mb-4 flex cursor-pointer flex-col items-center justify-center gap-1 rounded-xl border-2 border-dashed p-6 text-center text-sm ${
            dragging ? "border-[color:var(--fb-v2-accent)] bg-[color:var(--fb-v2-accent-soft)]" : "border-[color:var(--fb-v2-border-strong)]"
          }`}
        >
          <span className="font-medium">{file ? file.name : tr("Drop a CSV or Excel file here, or choose one")}</span>
          <span className="text-[color:var(--fb-v2-text-muted)]">{tr("Up to {mb} MB and {rows} rows. The first row is the header.", { mb: maxMb, rows: (meta?.max_rows ?? 200000).toLocaleString() })}</span>
          <input ref={input} type="file" accept=".csv,.tsv,.txt,.xlsx" className="sr-only" tabIndex={-1} onChange={(e) => pick(e.target.files?.[0])} />
        </div>
      ) : null}

      {kind === "sheet" ? (
        <>
          <Field label={tr("Published CSV link")} hint={tr("In Google Sheets: File, Share, Publish to the web, pick CSV, then copy the link.")}>
            <input className="v2-input w-full" dir="ltr" type="url" required value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://docs.google.com/spreadsheets/d/e/…/pub?output=csv" />
          </Field>
          <Field label={tr("Refresh")}>
            <select className="v2-input w-full sm:w-64" value={hours} onChange={(e) => setHours(e.target.value)}>
              <option value="0">{tr("Only when I ask")}</option>
              <option value="1">{tr("Every hour")}</option>
              <option value="6">{tr("Every 6 hours")}</option>
              <option value="24">{tr("Every day")}</option>
              <option value="168">{tr("Every week")}</option>
            </select>
          </Field>
        </>
      ) : null}

      {kind === "postgres" ? (
        meta && !meta.postgres_available ? (
          <Notice>{tr("Connecting databases needs encryption set up on the server first.")}</Notice>
        ) : (
          <>
            <Field
              label={tr("Connection string")}
              hint={tr("Use a database user that can only read the tables you want to share. The password is encrypted and never shown again.")}
            >
              <input
                className="v2-input w-full"
                dir="ltr"
                type="password"
                autoComplete="off"
                spellCheck={false}
                required
                value={dsn}
                onChange={(e) => setDsn(e.target.value)}
                placeholder="postgresql://reader:password@db.example.com:5432/sales"
              />
            </Field>
            <Field label={tr("Tables (optional)")} hint={tr("Comma separated. Leave empty to include up to 20 tables the user can read.")}>
              <input className="v2-input w-full" dir="ltr" value={tables} onChange={(e) => setTables(e.target.value)} placeholder="orders, customers" />
            </Field>
            {meta && !meta.allow_private_hosts ? <p className="mb-4 text-xs text-[color:var(--fb-v2-text-muted)]">{tr("Hosts on a private network are blocked unless an admin allows them.")}</p> : null}
          </>
        )
      ) : null}

      <Field label={tr("Name")}>
        <input className="v2-input w-full" required maxLength={120} value={name} onChange={(e) => setName(e.target.value)} />
      </Field>
      <Sharing value={visibility} team={team} teams={teams} onChange={(v, t) => (setVisibility(v), setTeam(t))} />
      {error ? <Notice kind="error">{error}</Notice> : null}
      <Button type="submit" disabled={busy}>
        {busy ? tr("Adding…") : tr("Add source")}
      </Button>
    </form>
  );
}
