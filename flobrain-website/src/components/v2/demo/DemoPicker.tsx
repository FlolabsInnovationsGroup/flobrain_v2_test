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
    <section aria-labelledby="demo-title" className="w-full max-w-3xl">
      <h2 id="demo-title" className="text-2xl font-semibold tracking-tight">
        {t(locale, "demo.title")}
      </h2>
      <p className="mt-1 max-w-xl text-[color:var(--fb-v2-text-muted)]">
        {t(locale, "demo.intro")}
      </p>

      <button
        type="button"
        onClick={() => go("owner", "/tour")}
        disabled={busy !== null}
        className="mt-5 flex w-full items-center justify-between gap-4 rounded-xl bg-[color:var(--fb-v2-accent)] px-5 py-4 text-start text-white hover:bg-[color:var(--fb-v2-accent-strong)] disabled:opacity-60"
      >
        <span>
          <span className="block text-lg font-semibold">{t(locale, "demo.fullTour")}</span>
          <span className="block text-sm opacity-90">{t(locale, "demo.fullTourText")}</span>
        </span>
        <span className="text-sm font-medium">{busy === "owner/tour" ? t(locale, "demo.opening") : t(locale, "demo.start")}</span>
      </button>

      <ul className="mt-4 grid gap-3 sm:grid-cols-2">
        {roles.map((role) => (
          <li key={role.key}>
            <button
              type="button"
              onClick={() => go(role.key)}
              disabled={busy !== null}
              className="flex h-full w-full flex-col gap-3 rounded-xl bg-[color:var(--fb-v2-surface)] p-4 text-start ring-1 ring-inset ring-[color:var(--fb-v2-border)] hover:ring-[color:var(--fb-v2-accent)] disabled:opacity-60"
            >
              <span className="flex items-center gap-3">
                <Avatar name={role.name} size={40} />
                <span>
                  <span className="block font-semibold">{role.name}</span>
                  <span className="block text-sm text-[color:var(--fb-v2-text-muted)]">{t(locale, `demo.roles.${role.key}`)}</span>
                </span>
              </span>
              <ul className="list-disc space-y-0.5 ps-5 text-sm">
                {(ROLE_HIGHLIGHTS[role.key]?.map((line) => tr(line)) ?? [role.description]).map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
              <span className="mt-auto text-sm font-medium text-[color:var(--fb-v2-accent)]">
                {busy === role.key ? t(locale, "demo.signingIn") : `${t(locale, "demo.signInAs")} ${role.name.split(" ")[0]}`}
              </span>
            </button>
          </li>
        ))}
      </ul>
      {error ? <Notice kind="error">{error}</Notice> : null}
    </section>
  );
}
