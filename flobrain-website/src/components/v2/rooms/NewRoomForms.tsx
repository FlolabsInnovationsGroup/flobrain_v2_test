"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { MemberPicker, type PickedMember } from "@/components/v2/rooms/MemberPicker";
import { Button } from "@/components/v2/ui/button";
import { Field, Notice } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, errorText } from "@/lib/v2/api";

/** Pick one person; opens the existing direct message with them or starts one. */
export function NewDirectMessage({ orgId, orgSlug, selfId, onCancel }: { orgId: string; orgSlug: string; selfId?: string; onCancel: () => void }) {
  const tr = useTr();
  const router = useRouter();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function start(member: PickedMember) {
    setBusy(true);
    setError("");
    try {
      const room = await api.post<{ id: string }>(`/orgs/${orgId}/rooms`, { user_id: member.id });
      router.push(`/w/${orgSlug}/rooms/${room.id}`);
    } catch (err) {
      setError(errorText(err));
      setBusy(false);
    }
  }

  return (
    <div className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
      <h2 className="mb-1 font-semibold">{tr("New direct message")}</h2>
      <p className="mb-3 text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Only the two of you can read a direct message. Admins can't open it.")}</p>
      {busy ? <Notice>{tr("Opening the conversation…")}</Notice> : <MemberPicker orgId={orgId} selfId={selfId} onPick={start} label={tr("Who do you want to message?")} />}
      {error ? <Notice kind="error">{error}</Notice> : null}
      <Button type="button" variant="ghost" className="mt-2" onClick={onCancel}>
        {tr("Cancel")}
      </Button>
    </div>
  );
}

/** A group room with a name and the people in it. Needs the "Manage rooms" permission. */
export function NewGroupRoom({ orgId, orgSlug, selfId, onCancel }: { orgId: string; orgSlug: string; selfId?: string; onCancel: () => void }) {
  const tr = useTr();
  const router = useRouter();
  const [name, setName] = useState("");
  const [picked, setPicked] = useState<PickedMember[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function create(event: React.FormEvent) {
    event.preventDefault();
    if (!name.trim()) {
      setError(tr("Give the room a name."));
      return;
    }
    setBusy(true);
    setError("");
    try {
      const room = await api.post<{ id: string }>(`/orgs/${orgId}/rooms`, { name: name.trim(), user_ids: picked.map((p) => p.id) });
      router.push(`/w/${orgSlug}/rooms/${room.id}`);
    } catch (err) {
      setError(errorText(err));
      setBusy(false);
    }
  }

  return (
    <form onSubmit={create} className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
      <h2 className="mb-1 font-semibold">{tr("New room")}</h2>
      <p className="mb-3 text-sm text-[color:var(--fb-v2-text-muted)]">
        {tr("A private group room. Only the people you add can read it, and admins can't open it.")}
      </p>
      <Field label={tr("Room name")}>
        <input className="v2-input" value={name} maxLength={200} onChange={(event) => setName(event.target.value)} />
      </Field>
      <div className="mb-3">
        <p className="mb-1 text-sm font-medium">{tr("People")}</p>
        {picked.length ? (
          <ul className="mb-2 flex flex-wrap gap-2">
            {picked.map((p) => (
              <li key={p.id}>
                <button
                  type="button"
                  className="rounded-full bg-[color:var(--fb-v2-border)] px-2 py-0.5 text-xs"
                  onClick={() => setPicked((rows) => rows.filter((r) => r.id !== p.id))}
                  aria-label={tr("Remove {name}", { name: p.name })}
                >
                  {p.name} ×
                </button>
              </li>
            ))}
          </ul>
        ) : null}
        <MemberPicker
          orgId={orgId}
          selfId={selfId}
          exclude={picked.map((p) => p.id)}
          onPick={(member) => setPicked((rows) => [...rows, member])}
          label={tr("Add people")}
        />
      </div>
      {error ? <Notice kind="error">{error}</Notice> : null}
      <div className="flex gap-2">
        <Button type="submit" disabled={busy}>
          {busy ? tr("Creating…") : tr("Create room")}
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel}>
          {tr("Cancel")}
        </Button>
      </div>
    </form>
  );
}
