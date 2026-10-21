"use client";

import { useEffect, useState } from "react";

import { Avatar, Notice } from "@/components/v2/ui/kit";
import { t, useLocale } from "@/i18n";
import { useTr } from "@/i18n/phrases";
import { errorText } from "@/lib/v2/api";
import { demoInfo, demoSignIn, ROLE_HIGHLIGHTS, type DemoRole } from "@/lib/v2/demo";


/**
 * The demo entrance on the sign-in page: pick a seat at Nile Labs, a made-up company
 * with a full workspace, and see FloBrain the way that person does. Hidden unless the
 * API runs with DEMO_MODE.
 */
export function DemoPicker() {
  const locale = useLocale();
  const tr = useTr();
  const [roles, setRoles] = useState<DemoRole[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    demoInfo().then((info) => setRoles(info.enabled ? (info.roles ?? []) : []));
  }, []);

  if (!roles || roles.length === 0) return null;

  async function go(role: string, landing = "") {
    setBusy(role + landing);
    setError("");
    try {
      window.location.assign(await demoSignIn(role, landing));
    } catch (err) {
      setError(errorText(err));
      setBusy(null);
    }
  }

  return (
    <section aria-labelledby="demo-title" className="mt-10 border-t border-[color:var(--fb-v2-border)] pt-8">
      <div className="flex items-baseline justify-between gap-3">
        <h2 id="demo-title" className="text-base font-semibold">
          {t(locale, "demo.title")}
        </h2>
        <span className="v2-mono text-[11px] text-[color:var(--fb-v2-text-faint)]">NILE LABS</span>
      </div>
      <p className="mt-1 text-sm text-[color:var(--fb-v2-text-muted)]">{t(locale, "demo.intro")}</p>

      <button
        type="button"
        onClick={() => go("owner", "/tour")}
        disabled={busy !== null}
        className="mt-4 flex w-full items-center justify-between gap-4 rounded-xl bg-[color:var(--fb-v2-accent)] px-4 py-3.5 text-start text-white shadow-[0_12px_30px_-12px_rgba(124,107,255,.9),inset_0_1px_0_rgba(255,255,255,.2)] transition-colors hover:bg-[color:var(--fb-v2-accent-strong)] disabled:opacity-60"
      >
        <span>
          <span className="block font-semibold">{t(locale, "demo.fullTour")}</span>
          <span className="block text-sm opacity-90">{t(locale, "demo.fullTourText")}</span>
        </span>
        <span className="shrink-0 text-sm font-medium">{busy === "owner/tour" ? t(locale, "demo.opening") : t(locale, "demo.start")}</span>
      </button>

      <ul className="mt-2.5 flex flex-col gap-2">
        {roles.map((role) => {
          const lines = ROLE_HIGHLIGHTS[role.key]?.map((line) => tr(line)) ?? [role.description];
          return (
            <li key={role.key}>
              <button
                type="button"
                onClick={() => go(role.key)}
                disabled={busy !== null}
                title={lines.join(". ")}
                className="flex w-full items-center gap-3 rounded-xl bg-[color:var(--fb-v2-surface)] p-3 text-start ring-1 ring-inset ring-[color:var(--fb-v2-border)] transition-shadow hover:ring-[color:var(--fb-v2-accent)] disabled:opacity-60"
              >
                <Avatar name={role.name} size={38} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-semibold">{role.name}</span>
                  <span className="block truncate text-[13px] text-[color:var(--fb-v2-text-muted)]">
                    {t(locale, `demo.roles.${role.key}`)}. {lines[0]}
                  </span>
                </span>
                <span className="shrink-0 text-[13px] font-medium text-[color:var(--fb-v2-accent)]">
                  {busy === role.key ? t(locale, "demo.signingIn") : `${t(locale, "demo.signInAs")} ${role.name.split(" ")[0]}`}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
      {error ? <Notice kind="error">{error}</Notice> : null}
    </section>
  );
}
