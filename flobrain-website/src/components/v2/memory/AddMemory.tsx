"use client";

import { useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { useTr } from "@/i18n/phrases";

import { CATEGORIES, MAX_TEXT, categoryLabel, textProblem, type Category } from "./types";

/** Write a memory by hand. The server still refuses anything sensitive. */
export function AddMemory({
  id,
  label,
  placeholder,
  blocked = [],
  onAdd,
}: {
  id: string;
  label: string;
  placeholder: string;
  blocked?: Category[];
  onAdd: (text: string, category: Category) => Promise<boolean>;
}) {
  const tr = useTr();
  const allowed = CATEGORIES.filter((c) => !blocked.includes(c));
  const [text, setText] = useState("");
  const [category, setCategory] = useState<Category>(allowed[0] ?? "other");
  const [busy, setBusy] = useState(false);
  const problem = text ? textProblem(tr, text) : "";

  return (
    <form
      className="flex flex-col gap-2 rounded-xl bg-[color:var(--fb-v2-surface)] p-4"
      onSubmit={async (e) => {
        e.preventDefault();
        if (!text.trim() || problem) return;
        setBusy(true);
        const ok = await onAdd(text.trim(), category);
        setBusy(false);
        if (ok) setText("");
      }}
    >
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <textarea id={id} className="v2-input min-h-16 w-full" dir="auto" maxLength={MAX_TEXT} placeholder={placeholder} value={text} onChange={(e) => setText(e.target.value)} />
      <div className="flex flex-wrap items-center gap-2">
        <label className="text-sm">
          <span className="sr-only">{tr("Category")}</span>
          <select className="v2-input w-auto" value={category} onChange={(e) => setCategory(e.target.value as Category)}>
            {allowed.map((c) => (
              <option key={c} value={c}>
                {categoryLabel(tr, c)}
              </option>
            ))}
          </select>
        </label>
        <span className="text-xs text-[color:var(--fb-v2-text-muted)]" aria-live="polite">
          {problem || tr("{n} of {max} characters", { n: text.trim().length, max: MAX_TEXT })}
        </span>
        <Button type="submit" className="ms-auto" disabled={busy || !text.trim() || !!problem}>
          {tr("Remember this")}
        </Button>
      </div>
    </form>
  );
}
