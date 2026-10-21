"use client";

import { useParams } from "next/navigation";
import QRCode from "qrcode";
import { useEffect, useState } from "react";

import { dirFor, useLocale } from "@/i18n";
import { useTr } from "@/i18n/phrases";
import { publicGet } from "@/lib/v2/api";
import "@/styles/v2-tokens.css";

type Verify = {
  data: {
    recipient: string;
    organization: string;
    kind: string;
    from: string | null;
    to: string;
    hours_total: number;
    hours_by_category: Record<string, number>;
    tasks_completed: number;
    projects: string[];
    projects_count?: number;
    learning_path?: string;
    issued_at?: string;
  };
  signature_valid: boolean;
  demo_key?: boolean;
  revoked: boolean;
  key_id: string;
  public_key: string;
};

/** Public certificate page: shows only the certificate's own data and whether its signature checks out. */
export default function VerifyPage() {
  const { slug } = useParams<{ slug: string }>();
  const locale = useLocale();
  const tr = useTr();
  const [cert, setCert] = useState<Verify | null>(null);
  const [missing, setMissing] = useState(false);
  const [qr, setQr] = useState("");

  useEffect(() => {
    publicGet<Verify>(`/verify/${encodeURIComponent(slug)}`)
      .then(setCert)
      .catch(() => setMissing(true));
    QRCode.toDataURL(window.location.href, { margin: 1, width: 160 }).then(setQr).catch(() => undefined);
  }, [slug]);

  const ok = cert && cert.signature_valid && !cert.revoked;
  return (
    <div className="v2-root flex min-h-dvh items-center justify-center p-6" dir={dirFor(locale)}>
      <main className="w-full max-w-2xl">
        {missing ? (
          <p role="alert">{tr("No certificate exists with this link.")}</p>
        ) : !cert ? (
          <p role="status">{tr("Checking the certificate…")}</p>
        ) : (
          <article className="rounded-2xl bg-[color:var(--fb-v2-surface)] p-8 ring-1 ring-inset ring-[color:var(--fb-v2-border)]">
            <p className="text-sm font-semibold" style={{ color: ok ? "var(--fb-v2-success)" : "var(--fb-v2-error)" }}>
              {tr(
                cert.revoked
                  ? "This certificate was revoked."
                  : cert.signature_valid
                    ? "Verified. Signed by FloBrain and unchanged since it was issued."
                    : "The signature does not match. Do not trust this certificate.",
              )}
            </p>
            {cert.demo_key ? (
              <p className="mt-2 text-sm font-medium" style={{ color: "var(--fb-v2-waiting)" }}>
                {tr("Signed with a demo key. This is a demo certificate, not a real one.")}
              </p>
            ) : null}
            <h1 className="mt-4 text-3xl font-semibold tracking-tight">{cert.data.recipient}</h1>
            <p className="mt-1 text-lg">
              {cert.data.kind === "internship_completion"
                ? tr("completed an internship at {org}", { org: cert.data.organization })
                : tr("completed the learning path “{path}” at {org}", { path: cert.data.learning_path ?? "", org: cert.data.organization })}
            </p>
            <p className="text-[color:var(--fb-v2-text-muted)]">
              {cert.data.from ? tr("{from} to {to}", { from: cert.data.from, to: cert.data.to }) : cert.data.to}
            </p>
            <dl className="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-3">
              <div>
                <dt className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Hours logged")}</dt>
                <dd className="text-2xl font-semibold">{cert.data.hours_total}</dd>
              </div>
              <div>
                <dt className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Tasks completed")}</dt>
                <dd className="text-2xl font-semibold">{cert.data.tasks_completed}</dd>
              </div>
              <div>
                <dt className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Projects")}</dt>
                <dd className="text-2xl font-semibold">{cert.data.projects_count ?? cert.data.projects.length}</dd>
              </div>
            </dl>
            {Object.keys(cert.data.hours_by_category).length ? (
              <p className="mt-4 text-sm">
                {Object.entries(cert.data.hours_by_category)
                  .map(([k, v]) => tr("{k}: {v} h", { k, v }))
                  .join(", ")}
              </p>
            ) : null}
            {cert.data.projects.length ? <p className="mt-2 text-sm">{tr("Projects: {projects}", { projects: cert.data.projects.join(", ") })}</p> : null}
            <div className="mt-6 flex flex-wrap items-end justify-between gap-4">
              <p className="max-w-sm break-all text-xs text-[color:var(--fb-v2-text-muted)]">
                {tr("Ed25519 key {id}. Public key {key}", { id: cert.key_id, key: cert.public_key })}
              </p>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              {qr ? <img src={qr} alt={tr("QR code linking to this page")} width={120} height={120} className="rounded bg-white p-1" /> : null}
            </div>
          </article>
        )}
      </main>
    </div>
  );
}
