"use client";

import { useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Badge, Section } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";

import { formatBytes } from "./logic";
import { RoomSelect } from "./RoomSelect";
import type { DocItem, Meta, Run } from "./types";

const REASON: Record<string, string> = {
  pdf_unavailable: "PDF text needs a library this server does not have yet",
  unsupported: "This file type can't be imported",
};

const KIND: Record<string, string> = {
  notion_page: "Page",
  notion_database: "Database",
  docx: "Word",
  pdf: "PDF",
  txt: "Text",
  md: "Markdown",
  csv: "CSV",
  html: "Web page",
};

/** Step 2 for Notion exports and files: pick what becomes a document, and the room it goes to. */
export function DocumentPicker({ run, meta, busy, onStart, onDiscard }: { run: Run; meta: Meta; busy: boolean; onStart: (m: { room_id: string; refs: string[] }) => void; onDiscard: () => void }) {
  const tr = useTr();
  const items: DocItem[] = run.preview?.items ?? [];
  const [chosen, setChosen] = useState<Set<string>>(() => new Set(items.filter((i) => i.supported).map((i) => i.ref)));
  const [room, setRoom] = useState("");
  const supported = items.filter((i) => i.supported);

  const toggle = (ref: string, on: boolean) =>
    setChosen((prev) => {
      const next = new Set(prev);
      if (on) next.add(ref);
      else next.delete(ref);
      return next;
    });

  return (
    <Section title={tr("Check and choose")} aside={<Badge tone="accent">{tr("Step 2 of 3")}</Badge>}>
      <div className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
        <RoomSelect rooms={meta.rooms} value={room} onChange={setRoom} />
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-sm">
          <span className="font-medium">{tr("{m} of {n} selected", { m: chosen.size, n: supported.length })}</span>
          <span className="flex gap-2">
            <Button type="button" variant="ghost" onClick={() => setChosen(new Set(supported.map((i) => i.ref)))}>
              {tr("Select all")}
            </Button>
            <Button type="button" variant="ghost" onClick={() => setChosen(new Set())}>
              {tr("Select none")}
            </Button>
          </span>
        </div>
        <ul className="max-h-96 divide-y divide-[color:var(--fb-v2-border)] overflow-y-auto">
          {items.map((i) => (
            <li key={i.ref} className="flex items-start gap-3 py-2 text-sm">
              <input
                type="checkbox"
                className="mt-1"
                disabled={!i.supported}
                checked={chosen.has(i.ref)}
                onChange={(e) => toggle(i.ref, e.target.checked)}
                aria-label={i.name}
              />
              <div className="min-w-0 flex-1">
                <p className="truncate">{i.name}</p>
                <p className="text-xs text-[color:var(--fb-v2-text-muted)]">
                  {tr(KIND[i.kind] ?? "File")} · {formatBytes(i.size)}
                  {i.notion_id ? ` · ${tr("Keeps a link to Notion")}` : ""}
                </p>
                {!i.supported ? <p className="text-xs text-[color:var(--fb-v2-error)]">{tr(REASON[i.reason] ?? REASON.unsupported)}</p> : null}
              </div>
            </li>
          ))}
        </ul>
        <p className="mt-4 text-sm text-[color:var(--fb-v2-text-muted)]">
          {tr("Each page or file becomes a document in the room, with a line saying where it came from. Only people who can open the room can read it.")}
        </p>
        <div className="mt-4 flex flex-wrap justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onDiscard} disabled={busy}>
            {tr("Discard")}
          </Button>
          <Button type="button" onClick={() => onStart({ room_id: room, refs: Array.from(chosen) })} disabled={busy || !room || !chosen.size}>
            {tr("Import {n} documents", { n: chosen.size })}
          </Button>
        </div>
      </div>
    </Section>
  );
}
