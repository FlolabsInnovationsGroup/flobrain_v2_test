"use client";

import { useId } from "react";

import { useTr } from "@/i18n/phrases";

import type { Place } from "./types";

/** The room imported documents go to. Only rooms the importer can open are listed. */
export function RoomSelect({ rooms, value, onChange }: { rooms: Place[]; value: string; onChange: (id: string) => void }) {
  const tr = useTr();
  const id = useId();
  return (
    <div className="mb-4 text-sm">
      <label htmlFor={id} className="mb-1 block font-medium">
        {tr("Room for the documents")}
      </label>
      <select id={id} className="v2-input w-full sm:w-80" value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{tr("Pick a room")}</option>
        {rooms.map((r) => (
          <option key={r.id} value={r.id}>
            {r.name}
          </option>
        ))}
      </select>
      <span className="mt-1 block text-[color:var(--fb-v2-text-muted)]">{tr("Everyone who can open this room will see the documents.")}</span>
    </div>
  );
}
