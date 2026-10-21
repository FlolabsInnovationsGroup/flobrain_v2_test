"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { t, useLocale } from "@/i18n";
import { roleLabel, type Access } from "@/lib/v2/access";
import { errorText } from "@/lib/v2/api";
import { demoReset, demoSignIn } from "@/lib/v2/demo";

const ROLES = ["owner", "admin", "lead", "member"] as const;

/** Shown only to demo users: who you are, switch seat, start over. */
export function DemoBar({ access }: { access: Access }) {
  const router = useRouter();
  const locale = useLocale();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  async function switchTo(role: string) {
    setBusy(true);
    try {
      window.location.assign(await demoSignIn(role));
    } catch (err) {
      setMessage(errorText(err));
      setBusy(false);
    }
  }

  async function reset() {
    setBusy(true);
    setMessage("");
    try {
      await demoReset();
      window.location.assign(await demoSignIn(access.demo_role || "owner"));
    } catch (err) {
      setMessage(errorText(err));
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-[color:var(--fb-v2-border)] bg-[color:var(--fb-v2-raised)] px-4 py-2 text-sm">
      <span>
        {t(locale, "demo.bar")} <strong>{roleLabel(access)}</strong>.
      </span>
      <label className="flex items-center gap-2">
        <span className="whitespace-nowrap text-[color:var(--fb-v2-text-muted)]">{t(locale, "demo.switchTo")}</span>
        <select
          className="v2-input w-auto py-1"
          value={access.demo_role || ""}
          disabled={busy}
          onChange={(event) => switchTo(event.target.value)}
        >
          {ROLES.map((key) => (
            <option key={key} value={key}>
              {t(locale, `demo.roles.${key}`)}
            </option>
          ))}
        </select>
      </label>
      <button
        type="button"
        className="underline-offset-2 hover:underline"
        disabled={busy}
        onClick={() => router.push(`/w/${access.org.slug}/tour`)}
      >
        {t(locale, "demo.tour")}
      </button>
      <button type="button" className="underline-offset-2 hover:underline" disabled={busy} onClick={reset}>
        {t(locale, "demo.restart")}
      </button>
      {message ? <span className="text-[color:var(--fb-v2-error)]">{message}</span> : null}
    </div>
  );
}
