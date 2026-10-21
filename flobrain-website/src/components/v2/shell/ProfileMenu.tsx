"use client";

import { LogOut, UserRound } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { Avatar } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { roleLabel } from "@/lib/v2/access";
import { useAccess } from "@/lib/v2/AccessContext";
import { api } from "@/lib/v2/api";
import { clearV2Tokens } from "@/lib/v2/client";
import { useCockpit } from "@/lib/v2/LayoutContext";
import { useOrgData } from "@/lib/v2/useOrgData";

/** Sign out: revoke the refresh token on the server (best effort), then forget both tokens here. */
export async function signOut() {
  const refresh = typeof window !== "undefined" ? window.localStorage.getItem("flobrain_refresh_token") : null;
  if (refresh) await api.post("/auth/signout", { refresh }).catch(() => undefined);
  clearV2Tokens();
  if (typeof window !== "undefined") {
    window.localStorage.removeItem("flobrain_demo_role");
    window.location.assign("/w/signin");
  }
}

export function ProfileMenu({ orgSlug }: { orgSlug: string }) {
  const tr = useTr();
  const { access } = useAccess();
  const { cockpit, save } = useCockpit();
  const low = cockpit.low_bandwidth;
  const me = useOrgData<{ username: string | null; email: string }>(null, "/me", { orgScoped: false });
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const name = me.data?.username || me.data?.email || "";

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !box.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);

  return (
    <div ref={box} className="relative">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={tr("Your account")}
        className="flex items-center rounded-full"
        onClick={() => setOpen((v) => !v)}
      >
        {low || !name ? <UserRound size={20} aria-hidden /> : <Avatar name={name} size={28} />}
      </button>
      {open ? (
        <div role="menu" className="absolute end-0 top-full z-50 mt-2 w-64 rounded-xl bg-[color:var(--fb-v2-surface)] p-2 shadow-lg ring-1 ring-[color:var(--fb-v2-border)]">
          <div className="px-3 py-2">
            <p className="truncate font-medium">{name}</p>
            {me.data?.username ? <p className="truncate text-sm text-[color:var(--fb-v2-text-muted)]">{me.data.email}</p> : null}
            {access ? <p className="text-xs text-[color:var(--fb-v2-text-muted)]">{roleLabel(access)}</p> : null}
          </div>
          <Link role="menuitem" href={`/w/${orgSlug}/settings/profile`} className="block rounded-lg px-3 py-2 text-sm hover:bg-[color:var(--fb-v2-border)]" onClick={() => setOpen(false)}>
            {tr("My profile")}
          </Link>
          {access ? (
            <Link role="menuitem" href={`/w/${orgSlug}/members/${access.user_id}`} className="block rounded-lg px-3 py-2 text-sm hover:bg-[color:var(--fb-v2-border)]" onClick={() => setOpen(false)}>
              {tr("How others see me")}
            </Link>
          ) : null}
          <Link role="menuitem" href={`/w/${orgSlug}/settings/access`} className="block rounded-lg px-3 py-2 text-sm hover:bg-[color:var(--fb-v2-border)]" onClick={() => setOpen(false)}>
            {tr("My access")}
          </Link>
          <label className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm hover:bg-[color:var(--fb-v2-border)]">
            <input type="checkbox" checked={low} onChange={(e) => void save({ low_bandwidth: e.target.checked }).catch(() => undefined)} />
            <span>
              {tr("Low-bandwidth mode")}
              <span className="block text-xs text-[color:var(--fb-v2-text-muted)]">{tr("No images or video, slower updates")}</span>
            </span>
          </label>
          <button
            role="menuitem"
            type="button"
            disabled={busy}
            className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-start text-sm hover:bg-[color:var(--fb-v2-border)]"
            onClick={async () => {
              setBusy(true);
              await signOut();
            }}
          >
            <LogOut size={16} aria-hidden />
            {busy ? tr("Signing out") : tr("Sign out")}
          </button>
        </div>
      ) : null}
    </div>
  );
}
