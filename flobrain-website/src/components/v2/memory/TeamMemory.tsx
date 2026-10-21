"use client";

import { useEffect, useState } from "react";

import { Notice, Rows } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, errorText, rowsOf } from "@/lib/v2/api";

import { AddMemory } from "./AddMemory";
import { MemoryRow } from "./MemoryRow";
import type { Category, MemoryItem, TeamRow } from "./types";

/** Managers (memory.manage): pick a team, then add, change or delete its notes. */
export function TeamMemory({ orgId, teams, enabled, blocked, onChanged }: { orgId: string; teams: TeamRow[]; enabled: boolean; blocked: Category[]; onChanged: () => void }) {
  const tr = useTr();
  const [teamId, setTeamId] = useState(teams[0]?.id ?? "");
  const [items, setItems] = useState<MemoryItem[] | null>(null);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const base = `/orgs/${orgId}/memory/teams/${teamId}/items`;

  useEffect(() => {
    if (!teamId) return;
    let live = true;
    api
      .get<MemoryItem[]>(`/orgs/${orgId}/memory/teams/${teamId}/items`)
      .then((rows) => live && setItems(rowsOf<MemoryItem>(rows)))
      .catch((err) => live && setMessage({ kind: "error", text: errorText(err) }));
    return () => {
      live = false;
    };
  }, [orgId, teamId]);

  async function reload() {
    setItems(rowsOf<MemoryItem>(await api.get<MemoryItem[]>(base)));
    onChanged();
  }

  async function act(fn: () => Promise<unknown>, ok: string) {
    setMessage(null);
    try {
      await fn();
      setMessage({ kind: "ok", text: ok });
      await reload();
      return true;
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
      return false;
    }
  }

  if (!teams.length) return <Notice>{tr("There are no teams yet.")}</Notice>;

  return (
    <div className="flex flex-col gap-4">
      <label className="block text-sm">
        <span className="mb-1 block font-medium">{tr("Team")}</span>
        <select
          className="v2-input w-auto"
          value={teamId}
          onChange={(e) => {
            setItems(null);
            setTeamId(e.target.value);
          }}
        >
          {teams.map((t) => (
            <option key={t.id} value={t.id}>
              {tr("{name} ({n} notes)", { name: t.name, n: t.memories })}
            </option>
          ))}
        </select>
      </label>
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}
      {enabled ? (
        <AddMemory
          id="team-memory-add"
          label={tr("Add a note for this team")}
          placeholder={tr("For example: code freeze starts two days before every release")}
          blocked={blocked}
          onAdd={(text, category) => act(() => api.post(base, { text, category }), tr("Saved for the team."))}
        />
      ) : (
        <Notice>{tr("Team memory is off in the rules. You can still delete notes.")}</Notice>
      )}
      {items === null ? (
        <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Loading…")}</p>
      ) : items.length ? (
        <Rows>
          {items.map((item) => (
            <MemoryRow
              key={item.id}
              item={item}
              editable
              blocked={blocked}
              onSave={(change) => act(() => api.patch(`${base}/${item.id}`, change), tr("Saved."))}
              onDelete={() => {
                if (window.confirm(tr("Delete this team note?"))) act(() => api.del(`${base}/${item.id}`), tr("Deleted."));
              }}
            />
          ))}
        </Rows>
      ) : (
        <Notice>{tr("No notes for this team yet.")}</Notice>
      )}
    </div>
  );
}
