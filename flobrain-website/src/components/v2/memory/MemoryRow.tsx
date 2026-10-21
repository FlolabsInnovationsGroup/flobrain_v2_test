"use client";

import { useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Badge, Row, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";

import { CATEGORIES, MAX_TEXT, categoryLabel, sourceLabel, textProblem, type Category, type MemoryItem } from "./types";

export type RowChange = { text?: string; category?: Category; pinned?: boolean };

/** One memory: what it says, where it came from, and (when editable) edit, pin and delete. */
export function MemoryRow({
  item,
  editable,
  blocked = [],
  onSave,
  onDelete,
}: {
  item: MemoryItem;
  editable: boolean;
  blocked?: Category[];
  onSave?: (change: RowChange) => Promise<boolean>;
  onDelete?: () => void;
}) {
  const tr = useTr();
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(item.text);
  const [category, setCategory] = useState<Category>(item.category);
  const problem = textProblem(tr, text);

  if (editing && onSave) {
    return (
      <Row className="flex-col items-stretch">
        <label className="block text-sm">
          <span className="sr-only">{tr("Memory text")}</span>
          <textarea className="v2-input min-h-16 w-full" dir="auto" maxLength={MAX_TEXT} value={text} onChange={(e) => setText(e.target.value)} />
        </label>
        <div className="flex flex-wrap items-center gap-2">
          <label className="text-sm">
            <span className="sr-only">{tr("Category")}</span>
            <select className="v2-input w-auto" value={category} onChange={(e) => setCategory(e.target.value as Category)}>
              {CATEGORIES.filter((c) => c === item.category || !blocked.includes(c)).map((c) => (
                <option key={c} value={c}>
                  {categoryLabel(tr, c)}
                </option>
              ))}
            </select>
          </label>
          <span className="text-xs text-[color:var(--fb-v2-text-muted)]" aria-live="polite">
            {problem || tr("{n} of {max} characters", { n: text.trim().length, max: MAX_TEXT })}
          </span>
          <span className="ms-auto flex gap-2">
            <Button
              disabled={!!problem}
              onClick={async () => {
                const change: RowChange = {};
                if (text.trim() !== item.text) change.text = text.trim();
                if (category !== item.category) change.category = category;
                if (!Object.keys(change).length || (await onSave(change))) setEditing(false);
              }}
            >
              {tr("Save")}
            </Button>
            <Button
              variant="ghost"
              onClick={() => {
                setText(item.text);
                setCategory(item.category);
                setEditing(false);
              }}
            >
              {tr("Cancel")}
            </Button>
          </span>
        </div>
      </Row>
    );
  }

  return (
    <Row>
      <div className="min-w-0 flex-1 basis-64">
        <p className="break-words" dir="auto">
          {item.text}
        </p>
        <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-[color:var(--fb-v2-text-muted)]">
          <Badge>{categoryLabel(tr, item.category)}</Badge>
          {item.pinned ? <Badge tone="accent">{tr("Pinned")}</Badge> : null}
          {item.team ? <span>{tr("Team {name}", { name: item.team.name })}</span> : <span>{sourceLabel(tr, item)}</span>}
          <span>{when(item.created_at)}</span>
          {item.last_used_at ? <span>{tr("Last used {when}", { when: when(item.last_used_at) })}</span> : <span>{tr("Not used yet")}</span>}
          {item.expires_at ? <span>{tr("Deleted on {when}", { when: when(item.expires_at) })}</span> : null}
        </p>
      </div>
      {editable ? (
        <div className="flex flex-wrap gap-2">
          {onSave ? (
            <>
              <Button variant="ghost" aria-pressed={item.pinned} onClick={() => onSave({ pinned: !item.pinned })}>
                {item.pinned ? tr("Unpin") : tr("Pin")}
              </Button>
              <Button variant="ghost" onClick={() => setEditing(true)}>
                {tr("Edit")}
              </Button>
            </>
          ) : null}
          {onDelete ? (
            <Button variant="danger" onClick={onDelete}>
              {tr("Delete")}
            </Button>
          ) : null}
        </div>
      ) : null}
    </Row>
  );
}
