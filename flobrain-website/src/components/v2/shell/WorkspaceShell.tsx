"use client";

import { Menu, X } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { RightRail } from "@/components/v2/screens/CockpitScreen";
import { RoomsSidebar } from "@/components/v2/screens/RoomsSidebar";
import { ToolsRail } from "@/components/v2/screens/ToolsRail";
import { WorkspaceHeader } from "@/components/v2/screens/WorkspaceHeader";
import { LOCALES, setLocale, t, useLocale, type V2Locale } from "@/i18n";
import { useTr } from "@/i18n/phrases";
import { flag, navFor } from "@/lib/v2/access";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, rowsOf } from "@/lib/v2/api";
import { roomTabHref, useLayout } from "@/lib/v2/LayoutContext";
import { roomFromHref } from "@/lib/v2/layoutRules";
import { cn } from "@/lib/utils";

import { BrandMark } from "./BrandMark";
import { DemoBar } from "./DemoBar";
import { ICONS } from "./icons";
import { usePageViews } from "./usePageViews";
import { VideoTile } from "./VideoTile";

export function WorkspaceShell({ orgSlug, children }: { orgSlug: string; children: React.ReactNode }) {
  const { access, orgId } = useAccess();
  const { cockpit, layout, lowBandwidth } = useLayout();
  const router = useRouter();
  const locale = useLocale();
  const tr = useTr();
  const pathname = usePathname();
  const [openFor, setOpenFor] = useState<string | null>(null);
  const [waiting, setWaiting] = useState(0);
  const [changes, setChanges] = useState(0);
  const open = openFor !== null && openFor === pathname;

  useEffect(() => {
    if ("serviceWorker" in navigator && process.env.NODE_ENV === "production") {
      navigator.serviceWorker.register("/sw.js").catch(() => undefined);
    }
  }, []);

  useEffect(() => {
    const bump = () => setChanges((n) => n + 1);
    window.addEventListener("flobrain:approvals-changed", bump);
    return () => window.removeEventListener("flobrain:approvals-changed", bump);
  }, []);

  useEffect(() => {
    if (!orgId || !access?.flags.ai_actions) return;
    let cancelled = false;
    api
      .get(`/orgs/${orgId}/actions`)
      .then((value) => {
        if (!cancelled) setWaiting(rowsOf<{ status: string }>(value).filter((row) => row.status === "proposed").length);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [orgId, access, pathname, changes]);

  usePageViews(orgId, orgSlug, !!access?.org.demo);

  // Nav labels are catalog keys ("nav.tasks") or, for newer entries, English phrases.
  const label = (key: string) => (key.startsWith("nav.") ? t(locale, key) : tr(key));

  /** A room link in the sidebar opens the saved default room tab (cockpit layout). */
  function openDefaultTab(event: React.MouseEvent) {
    const tab = layout.default_room_tab;
    if (!tab || tab === "chat" || event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
    const anchor = (event.target as HTMLElement).closest("a");
    const roomId = anchor ? roomFromHref(anchor.getAttribute("href") || "", orgSlug) : null;
    if (!roomId || pathname?.includes(roomId)) return;
    event.preventDefault();
    router.push(roomTabHref(orgSlug, roomId, tab));
  }

  const groups = navFor(orgSlug, access);
  const nav = (
    <nav aria-label={tr("Workspace")} className="flex h-full flex-col overflow-y-auto">
      <div className="px-4 pb-3 pt-4">
        <Link href={`/w/${orgSlug}`} className="flex items-center gap-2.5 rounded-lg px-1 py-1 text-[15px] font-semibold tracking-tight">
          <BrandMark size={24} />
          <span className="truncate">{access?.org.name ?? "FloBrain"}</span>
        </Link>
      </div>
      {groups.map((group) => (
        <div key={group.label} className="px-3 pb-3">
          <p className="v2-mono mb-1 px-2 text-[11px] font-medium tracking-wide text-[color:var(--fb-v2-text-faint)]">{label(group.label)}</p>
          <ul>
            {group.items.map((item) => {
              const Icon = ICONS[item.icon];
              const active = item.href === `/w/${orgSlug}` ? pathname === item.href : pathname?.startsWith(item.href);
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "flex items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm text-[color:var(--fb-v2-text-muted)] transition-colors hover:bg-[color:var(--fb-v2-border)] hover:text-[color:var(--fb-v2-text)]",
                      active && "bg-[color:var(--fb-v2-raised)] font-medium text-[color:var(--fb-v2-text)] shadow-[inset_0_0_0_1px_var(--fb-v2-border-strong)]",
                    )}
                  >
                    {Icon ? <Icon size={16} aria-hidden /> : null}
                    <span className="flex-1">{label(item.label)}</span>
                    {item.badge === "approvals" && waiting > 0 ? (
                      <span
                        className="rounded-full bg-[color:var(--fb-v2-waiting)] px-1.5 text-xs font-semibold text-black"
                        aria-label={`${waiting} ${t(locale, "nav.waiting")}`}
                      >
                        {waiting}
                      </span>
                    ) : null}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
      {layout.panels.video && flag(access, "voice_video") ? <VideoTile /> : null}
      {layout.panels.rooms ? (
        <div onClickCapture={openDefaultTab}>
          <RoomsSidebar orgSlug={orgSlug} embedded />
        </div>
      ) : null}
      <div className="mt-auto px-5 py-4">
        <label className="block text-sm">
          <span className="sr-only">{t(locale, "nav.languageLabel")}</span>
          <select className="v2-input py-1" value={locale} onChange={(e) => setLocale(e.target.value as V2Locale)} aria-label={t(locale, "nav.languageLabel")}>
            {LOCALES.map((l) => (
              <option key={l.code} value={l.code} lang={l.code}>
                {l.name}
              </option>
            ))}
          </select>
        </label>
      </div>
    </nav>
  );

  return (
    <div
      className={cn("flex min-h-dvh flex-col", lowBandwidth && "[&_img]:hidden [&_video]:hidden")}
      data-low-bandwidth={lowBandwidth || undefined}
      style={layout.accent ? ({ "--fb-v2-accent": layout.accent, "--fb-v2-accent-strong": layout.accent } as React.CSSProperties) : undefined}
    >
      {access?.demo_role ? <DemoBar access={access} /> : null}
      <div className="flex min-h-0 flex-1">
        {cockpit.mode !== "focus" || !layout.panels.compact ? <ToolsRail orgSlug={orgSlug} /> : null}
        <aside className="hidden w-64 shrink-0 border-e border-[color:var(--fb-v2-border)] bg-[linear-gradient(180deg,var(--fb-v2-surface),var(--fb-v2-page)_60%)] lg:block">{nav}</aside>
        {open ? (
          <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label={t(locale, "nav.menu")}>
            <button
              type="button"
              aria-label={t(locale, "nav.closeMenu")}
              className="absolute inset-0 bg-black/50"
              onClick={() => setOpenFor(null)}
            />
            <aside className="absolute inset-y-0 start-0 w-72 bg-[color:var(--fb-v2-page)]">
              <button type="button" aria-label={t(locale, "nav.closeMenu")} className="absolute end-3 top-4" onClick={() => setOpenFor(null)}>
                <X size={18} />
              </button>
              {nav}
            </aside>
          </div>
        ) : null}
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex items-center gap-2 border-b border-[color:var(--fb-v2-border)] bg-[color:color-mix(in_srgb,var(--fb-v2-page)_85%,transparent)] backdrop-blur">
            <button type="button" className="p-3 lg:hidden" aria-label={t(locale, "nav.openMenu")} onClick={() => setOpenFor(pathname)}>
              <Menu size={20} />
            </button>
            <div className="min-w-0 flex-1">
              <WorkspaceHeader orgSlug={orgSlug} />
            </div>
          </div>
          <div className="flex min-h-0 flex-1">
            <main className="min-w-0 flex-1 px-4 py-6 md:px-8">{children}</main>
            {layout.panels.right_rail && pathname !== `/w/${orgSlug}` ? <RightRail orgSlug={orgSlug} /> : null}
          </div>
        </div>
      </div>
    </div>
  );
}
