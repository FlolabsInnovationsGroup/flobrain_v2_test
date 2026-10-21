"use client";

import { useEffect, useState } from "react";

import { Avatar } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, rowsOf } from "@/lib/v2/api";

export type PickedMember = { id: string; name: string };

type MemberRow = { id: string; username?: string | null; avatar_url?: string | null };

/** Search active members of the org and pick one. People already picked (and you) are hidden. */
export function MemberPicker({
  orgId,
  selfId,
  exclude = [],
  onPick,
  label,
}: {
  orgId: string;
  selfId?: string;
  exclude?: string[];
  onPick: (member: PickedMember) => void;
  label: string;
}) {
  const tr = useTr();
  const [query, setQuery] = useState("");
  const [rows, setRows] = useState<MemberRow[]>([]);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const timer = window.setTimeout(() => {
      const params: Record<string, string> = { status: "active", page_size: "20" };
      if (query.trim()) params.q = query.trim();
      api
        .get<unknown>(`/orgs/${orgId}/members`, params)
        .then((value) => {
          if (cancelled) return;
          setRows(rowsOf<MemberRow>(value));
          setFailed(false);
        })
        .catch(() => !cancelled && setFailed(true));
    }, 250);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [orgId, query]);

  const hidden = new Set([...(selfId ? [selfId] : []), ...exclude]);
  const shown = rows.filter((row) => !hidden.has(row.id));

  return (
    <div>
      <input
        className="v2-input mb-2"
        aria-label={label}
        placeholder={tr("Search people by name")}
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />
      {failed ? <p className="text-sm text-[color:var(--fb-v2-error)]">{tr("Could not load people")}</p> : null}
      <ul className="max-h-60 space-y-1 overflow-y-auto">
        {shown.map((row) => {
          const name = row.username || tr("Member");
          return (
            <li key={row.id}>
              <button
                type="button"
                className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-start text-sm hover:bg-[color:var(--fb-v2-border)]"
                onClick={() => onPick({ id: row.id, name })}
              >
                <Avatar name={name} size={24} />
                <span>{name}</span>
              </button>
            </li>
          );
        })}
        {!failed && shown.length === 0 ? (
          <li className="px-2 text-sm text-[color:var(--fb-v2-text-muted)]">{tr("No one matches")}</li>
        ) : null}
      </ul>
    </div>
  );
}
