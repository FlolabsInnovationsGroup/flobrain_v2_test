"use client";

import { useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Badge, Notice } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";

import { ConnectedPicker } from "./ConnectedPicker";
import type { Meta, Run } from "./types";
import { UploadBox } from "./UploadBox";

export type SourceKey = "slack" | "notion" | "drive";

const CARDS: { key: SourceKey; name: string; blurb: string }[] = [
  { key: "slack", name: "Slack", blurb: "Channels and their history, with threads and who said what." },
  { key: "notion", name: "Notion", blurb: "Pages and databases, as documents in a room." },
  { key: "drive", name: "Google Drive", blurb: "Google Docs, Word files and text files, as documents." },
];

/** Step 1: the three sources as cards. */
export function SourceCards({ value, onPick }: { value: SourceKey | null; onPick: (k: SourceKey) => void }) {
  const tr = useTr();
  return (
    <div className="mb-6 grid gap-3 sm:grid-cols-3" role="radiogroup" aria-label={tr("Where to import from")}>
      {CARDS.map((c) => (
        <button
          key={c.key}
          type="button"
          role="radio"
          aria-checked={value === c.key}
          onClick={() => onPick(c.key)}
          className={`v2-card rounded-xl p-4 text-start transition ${value === c.key ? "ring-2 ring-[color:var(--fb-v2-accent)]" : "hover:bg-[color:var(--fb-v2-raised)]"}`}
        >
          <span className="block text-base font-semibold">{c.name}</span>
          <span className="mt-1 block text-sm text-[color:var(--fb-v2-text-muted)]">{tr(c.blurb)}</span>
        </button>
      ))}
    </div>
  );
}

function Steps({ items }: { items: string[] }) {
  const tr = useTr();
  return (
    <ol className="mb-4 list-decimal space-y-1 ps-5 text-sm">
      {items.map((s) => (
        <li key={s}>{tr(s)}</li>
      ))}
    </ol>
  );
}

const SLACK_STEPS = [
  "In Slack, click your workspace name, then Tools & settings, then Workspace settings.",
  "Open Import/Export Data and choose Export.",
  "Pick the dates and start the export. Slack emails you when the file is ready.",
  "Download the ZIP file and upload it here. Don't unzip it.",
];
const NOTION_STEPS = [
  "In Notion, open Settings, then Workspace, then Export all workspace content. For one page, use ••• then Export.",
  "Choose Markdown & CSV and include subpages.",
  "Download the ZIP file and upload it here.",
];
const TAKEOUT_STEPS = [
  "Go to takeout.google.com, choose Deselect all, then tick Drive.",
  "Export once as a ZIP file and download it.",
  "Upload the ZIP here, or upload single files.",
];

/** Step 1, continued: how to get the data out of the source, then upload or pick. */
export function SourcePanel({ source, orgId, meta, busy, onRun, onSample }: { source: SourceKey; orgId: string; meta: Meta; busy: boolean; onRun: (r: Run) => void; onSample: (s: "slack" | "notion") => void }) {
  const tr = useTr();
  const [notionMode, setNotionMode] = useState<"connected" | "export">(meta.notion.length ? "connected" : "export");
  const box = "rounded-xl bg-[color:var(--fb-v2-surface)] p-4";

  if (source === "slack") {
    return (
      <div className={box}>
        <h2 className="mb-2 text-lg font-semibold">{tr("Import a Slack export")}</h2>
        <Steps items={SLACK_STEPS} />
        <p className="mb-4 text-sm text-[color:var(--fb-v2-text-muted)]">
          {tr("Only Slack workspace owners and admins can export. Private channels and direct messages are only in exports from paid plans that include them.")}
        </p>
        <UploadBox orgId={orgId} source="slack" maxMb={meta.max_upload_mb} maxFiles={1} hint={tr("Your Slack export (.zip)")} onUploaded={onRun} />
        {meta.demo ? <Sample label={tr("Try the sample Slack export")} onClick={() => onSample("slack")} busy={busy} /> : null}
      </div>
    );
  }

  if (source === "notion") {
    return (
      <div className={box}>
        <h2 className="mb-2 text-lg font-semibold">{tr("Import from Notion")}</h2>
        <div role="tablist" aria-label={tr("How to import")} className="mb-4 flex flex-wrap gap-2">
          {(["connected", "export"] as const).map((m) => (
            <button
              key={m}
              type="button"
              role="tab"
              aria-selected={notionMode === m}
              onClick={() => setNotionMode(m)}
              className={`rounded-full px-3 py-1 text-sm ${notionMode === m ? "bg-[color:var(--fb-v2-accent)] text-white" : "bg-[color:var(--fb-v2-raised)]"}`}
            >
              {m === "connected" ? tr("Connected Notion") : tr("Export file")}
            </button>
          ))}
        </div>
        {notionMode === "connected" ? (
          meta.notion.length ? (
            <>
              {meta.notion.some((c) => c.simulated) ? <Badge>{tr("Simulated in the demo")}</Badge> : null}
              <ConnectedPicker orgId={orgId} meta={meta} kind="notion" onStarted={onRun} />
            </>
          ) : (
            <Notice>{tr("Notion isn't connected. An admin can connect it in Integrations with an internal integration token, then share pages with that integration.")}</Notice>
          )
        ) : (
          <>
            <Steps items={NOTION_STEPS} />
            <UploadBox orgId={orgId} source="notion_zip" maxMb={meta.max_upload_mb} maxFiles={1} hint={tr("Your Notion export (.zip)")} onUploaded={onRun} />
            {meta.demo ? <Sample label={tr("Try the sample Notion export")} onClick={() => onSample("notion")} busy={busy} /> : null}
          </>
        )}
      </div>
    );
  }

  return (
    <div className={box}>
      <h2 className="mb-2 text-lg font-semibold">{tr("Import from Google Drive")}</h2>
      {meta.drive.status === "ready" ? (
        <>
          {meta.drive.simulated ? <Badge>{tr("Simulated in the demo")}</Badge> : null}
          <ConnectedPicker orgId={orgId} meta={meta} kind="drive" onStarted={onRun} />
          <h3 className="mb-2 mt-6 text-sm font-semibold">{tr("Or upload files")}</h3>
        </>
      ) : (
        <>
          <Notice>{meta.drive.status === "needs_scope" ? tr("Your Google connection can't read Drive yet. Reconnect it with Drive read access, or upload files instead.") : tr("Google Workspace isn't connected. You can still upload a Google Takeout file or single files.")}</Notice>
          <Steps items={TAKEOUT_STEPS} />
        </>
      )}
      {!meta.pdf_supported ? <p className="mb-3 text-sm text-[color:var(--fb-v2-text-muted)]">{tr("PDF files are listed but skipped for now: this server can't read PDF text yet.")}</p> : null}
      <UploadBox
        orgId={orgId}
        source="files"
        maxMb={meta.max_upload_mb}
        maxFiles={meta.max_files_per_upload}
        hint={tr("A Google Takeout ZIP, or .docx, .pdf, .txt, .md, .csv and .html files")}
        onUploaded={onRun}
      />
    </div>
  );
}

function Sample({ label, onClick, busy }: { label: string; onClick: () => void; busy: boolean }) {
  const tr = useTr();
  return (
    <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-[color:var(--fb-v2-border)] pt-4 text-sm">
      <span className="text-[color:var(--fb-v2-text-muted)]">{tr("Demo workspace: a small export with fake people is ready to try.")}</span>
      <Button type="button" variant="outline" onClick={onClick} disabled={busy}>
        {label}
      </Button>
    </div>
  );
}
