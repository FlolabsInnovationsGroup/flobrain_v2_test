"use client";

import { Bell, Moon, Search, Sun } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import { useEffect, useState, useSyncExternalStore } from "react";

import { ProfileMenu } from "@/components/v2/shell/ProfileMenu";
import { ReportProblem } from "@/components/v2/shell/ReportProblem";
import { TopBarTimer } from "@/components/v2/timer/TopBarTimer";
import { useTr } from "@/i18n/phrases";
import { useAccess } from "@/lib/v2/AccessContext";
import { v2Client } from "@/lib/v2/client";
import { useLayout, type CockpitMode } from "@/lib/v2/LayoutContext";
import { cn } from "@/lib/utils";

const MODES: { value: CockpitMode; label: string }[] = [
  { value: "default", label: "mode|Default" },
  { value: "focus", label: "mode|Focus" },
  { value: "custom", label: "mode|Custom" },
];

const noop = () => () => undefined;

/** Light and dark both have V2 tokens (``.light .v2-root`` in v2-tokens.css), so the switch is real. */
function ThemeSwitch() {
  const tr = useTr();
  const { resolvedTheme, theme, setTheme } = useTheme();
  const mounted = useSyncExternalStore(noop, () => true, () => false);
  if (!mounted) return <span className="h-8 w-8" aria-hidden />;
  const dark = (resolvedTheme ?? theme) !== "light";
  return (
    <button
      type="button"
      className="rounded-lg p-1.5 hover:bg-[color:var(--fb-v2-border)]"
      aria-label={dark ? tr("Switch to light theme") : tr("Switch to dark theme")}
      title={dark ? tr("Switch to light theme") : tr("Switch to dark theme")}
      onClick={() => setTheme(dark ? "light" : "dark")}
    >
      {dark ? <Sun size={18} aria-hidden /> : <Moon size={18} aria-hidden />}
    </button>
  );
}

/**
 * Top bar (spec 10.1): org switcher, cockpit mode switch (when the org has the ``cockpit`` flag),
 * the timer, search, notifications, theme, Report a problem and the account menu, on one line.
 */
export function WorkspaceHeader({ orgSlug }: { orgSlug: string }) {
  const { orgId } = useAccess();
  const router = useRouter();
  const tr = useTr();
  const { cockpit, save, enabled } = useLayout();
  const [orgs, setOrgs] = useState<Array<{ slug: string; name: string }>>([]);

  useEffect(() => {
    v2Client()
      .orgs()
      .then((rows) => setOrgs(rows))
      .catch(() => undefined);
  }, []);

  const icon = "rounded-lg p-1.5 hover:bg-[color:var(--fb-v2-border)]";
  return (
    <header className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2 px-4 py-2">
      <div className="flex min-w-0 items-center gap-3">
        <label className="text-sm text-[color:var(--fb-v2-text-muted)]">
          <span className="sr-only">{tr("Workspace")}</span>
          <select
            className="max-w-40 truncate bg-transparent"
            aria-label={tr("Workspace")}
            value={orgSlug}
            onChange={(event) => router.push(`/w/${event.target.value}`)}
          >
            {orgs.length === 0 ? <option value={orgSlug}>{orgSlug}</option> : null}
            {orgs.map((org) => (
              <option key={org.slug} value={org.slug}>
                {org.name}
              </option>
            ))}
          </select>
        </label>
        {enabled ? (
          <div role="radiogroup" aria-label={tr("Cockpit view")} className="hidden gap-0.5 rounded-[11px] bg-[color:var(--fb-v2-surface)] p-[3px] ring-1 ring-inset ring-[color:var(--fb-v2-border)] sm:inline-flex">
            {MODES.map((m) => (
              <button
                key={m.value}
                type="button"
                role="radio"
                aria-checked={cockpit.mode === m.value}
                onClick={() => void save({ mode: m.value }).catch(() => undefined)}
                className={cn(
                  "rounded-lg px-3 py-1 text-[13px] font-medium text-[color:var(--fb-v2-text-faint)] transition-colors hover:text-[color:var(--fb-v2-text)]",
                  cockpit.mode === m.value && "bg-[color:var(--fb-v2-raised)] text-[color:var(--fb-v2-text)] shadow-[inset_0_0_0_1px_var(--fb-v2-border-strong)]",
                )}
              >
                {tr(m.label)}
              </button>
            ))}
          </div>
        ) : null}
      </div>
      <div className="flex items-center gap-1.5">
        <TopBarTimer orgId={orgId} />
        <Link href={`/w/${orgSlug}/search`} className={icon} aria-label={tr("Search")} title={tr("Search")}>
          <Search size={18} aria-hidden />
        </Link>
        <Link href={`/w/${orgSlug}/notifications`} className={icon} aria-label={tr("Inbox")} title={tr("Inbox")}>
          <Bell size={18} aria-hidden />
        </Link>
        <ThemeSwitch />
        <ReportProblem orgSlug={orgSlug} />
        <ProfileMenu orgSlug={orgSlug} />
      </div>
    </header>
  );
}
