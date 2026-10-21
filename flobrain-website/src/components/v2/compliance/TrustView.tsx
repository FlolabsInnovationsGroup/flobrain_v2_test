"use client";

import { useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Field, Notice } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";

import { Pct, ReadinessBar, inputClass } from "./bits";
import type { TrustPublic } from "./types";

type RequestState = { kind: "ok" | "error"; key: "sent" | "invalid" | "tooMany" | "failed" } | null;

/** The public trust page body. ``onRequest`` is absent in the editor preview (the form is shown but inert). */
export function TrustView({ data, onRequest }: { data: TrustPublic; onRequest?: (body: Record<string, unknown>) => Promise<number> }) {
  const tr = useTr();
  const [picked, setPicked] = useState<string[]>([]);
  const [form, setForm] = useState({ name: "", email: "", company: "", message: "", website: "" });
  const [state, setState] = useState<RequestState>(null);
  const [busy, setBusy] = useState(false);
  const shown = new Set(data.sections);

  async function send() {
    if (!onRequest) return;
    setBusy(true);
    setState(null);
    try {
      const status = await onRequest({ ...form, documents: picked });
      if (status === 202) {
        setState({ kind: "ok", key: "sent" });
        setForm({ name: "", email: "", company: "", message: "", website: "" });
        setPicked([]);
      } else setState({ kind: "error", key: status === 400 ? "invalid" : status === 429 ? "tooMany" : "failed" });
    } finally {
      setBusy(false);
    }
  }

  const note =
    state?.key === "sent"
      ? tr("Thanks. The team will check your request and answer by email.")
      : state?.key === "invalid"
        ? tr("Enter your name and a valid work email.")
        : state?.key === "tooMany"
          ? tr("Too many requests. Try again later.")
          : tr("Something went wrong. Try again later.");

  return (
    <div className="space-y-8">
      <header>
        <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{data.org.name}</p>
        <h1 className="text-3xl font-semibold tracking-tight" dir="auto">
          {data.headline}
        </h1>
        <p className="mt-2 rounded-lg bg-[color:var(--fb-v2-surface)] px-3 py-2 text-sm text-[color:var(--fb-v2-text-muted)]">
          {tr("Readiness, not certification: these numbers come from automated checks and our own attestations, not from an auditor.")}
        </p>
      </header>

      {shown.has("overview") && data.overview ? (
        <section aria-labelledby="trust-overview">
          <h2 id="trust-overview" className="mb-2 text-lg font-semibold">
            {tr("Security overview")}
          </h2>
          <p className="whitespace-pre-line leading-relaxed" dir="auto">
            {data.overview}
          </p>
        </section>
      ) : null}

      {shown.has("controls") && data.controls?.length ? (
        <section aria-labelledby="trust-controls">
          <h2 id="trust-controls" className="mb-3 text-lg font-semibold">
            {tr("Control readiness")}
          </h2>
          <div className="grid gap-4 md:grid-cols-2">
            {data.controls.map((fw) => (
              <div key={fw.framework} className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
                <div className="mb-2 flex items-baseline justify-between gap-3">
                  <h3 className="font-medium">{fw.name}</h3>
                  <span className="text-xl font-semibold">
                    <Pct value={fw.readiness} />
                  </span>
                </div>
                <ReadinessBar value={fw.readiness} label={fw.name} />
                <p className="v2-mono mt-1 text-xs text-[color:var(--fb-v2-text-muted)]">{tr("{n} of {total} applicable controls ready", { n: fw.passing, total: fw.applicable })}</p>
                <ul className="mt-3 space-y-1.5">
                  {fw.groups.map((g) => (
                    <li key={g.name} className="grid grid-cols-[minmax(0,1fr)_4rem_2.5rem] items-center gap-2 text-sm">
                      <span className="truncate" title={g.name}>
                        {g.name}
                      </span>
                      <ReadinessBar size="sm" value={g.readiness} label={g.name} />
                      <span className="text-end text-xs">
                        <Pct value={g.readiness} />
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {shown.has("subprocessors") && data.subprocessors?.length ? (
        <section aria-labelledby="trust-subs">
          <h2 id="trust-subs" className="mb-3 text-lg font-semibold">
            {tr("Subprocessors")}
          </h2>
          <div className="overflow-x-auto rounded-xl bg-[color:var(--fb-v2-surface)]">
            <table className="w-full min-w-[32rem] text-sm">
              <thead className="text-[color:var(--fb-v2-text-muted)]">
                <tr>
                  <th className="px-4 py-2 text-start font-medium">{tr("Company")}</th>
                  <th className="px-4 py-2 text-start font-medium">{tr("What they do for us")}</th>
                  <th className="px-4 py-2 text-start font-medium">{tr("Location")}</th>
                </tr>
              </thead>
              <tbody>
                {data.subprocessors.map((s, i) => (
                  <tr key={i} className="border-t border-[color:var(--fb-v2-border)]">
                    <td className="px-4 py-2 font-medium" dir="auto">
                      {s.website ? (
                        <a href={s.website} target="_blank" rel="noopener noreferrer" className="underline underline-offset-2">
                          {s.name}
                        </a>
                      ) : (
                        s.name
                      )}
                    </td>
                    <td className="px-4 py-2" dir="auto">
                      {s.purpose}
                    </td>
                    <td className="px-4 py-2" dir="auto">
                      {s.location}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {shown.has("data_location") && data.data_location ? (
        <section aria-labelledby="trust-location">
          <h2 id="trust-location" className="mb-2 text-lg font-semibold">
            {tr("Where your data is stored")}
          </h2>
          <p dir="auto">{data.data_location}</p>
        </section>
      ) : null}

      {shown.has("documents") && data.documents?.length ? (
        <section aria-labelledby="trust-docs">
          <h2 id="trust-docs" className="mb-1 text-lg font-semibold">
            {tr("Documents on request")}
          </h2>
          <p className="mb-3 text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Pick what you need. The team checks each request before sending anything.")}</p>
          <form
            className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4"
            onSubmit={(e) => {
              e.preventDefault();
              send();
            }}
          >
            <fieldset className="mb-4">
              <legend className="sr-only">{tr("Documents")}</legend>
              <ul className="grid gap-2 sm:grid-cols-2">
                {data.documents.map((d) => (
                  <li key={d.key}>
                    <label className="flex items-start gap-2 text-sm">
                      <input
                        type="checkbox"
                        className="mt-1"
                        checked={picked.includes(d.key)}
                        onChange={(e) => setPicked(e.target.checked ? [...picked, d.key] : picked.filter((k) => k !== d.key))}
                      />
                      <span>
                        <span className="block font-medium" dir="auto">
                          {d.title}
                        </span>
                        {d.description ? (
                          <span className="block text-[color:var(--fb-v2-text-muted)]" dir="auto">
                            {d.description}
                          </span>
                        ) : null}
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
            </fieldset>
            <div className="grid gap-x-4 sm:grid-cols-2">
              <Field label={tr("Your name")}>
                <input className={inputClass} required maxLength={120} autoComplete="name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
              </Field>
              <Field label={tr("Work email")}>
                <input className={inputClass} required type="email" dir="ltr" autoComplete="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
              </Field>
              <Field label={tr("Company")}>
                <input className={inputClass} maxLength={160} autoComplete="organization" value={form.company} onChange={(e) => setForm({ ...form, company: e.target.value })} />
              </Field>
              <Field label={tr("Message (optional)")}>
                <input className={inputClass} maxLength={1000} value={form.message} onChange={(e) => setForm({ ...form, message: e.target.value })} />
              </Field>
            </div>
            <div aria-hidden className="absolute -left-[9999px] h-px w-px overflow-hidden">
              <label>
                Website
                <input tabIndex={-1} autoComplete="off" value={form.website} onChange={(e) => setForm({ ...form, website: e.target.value })} />
              </label>
            </div>
            {state ? <Notice kind={state.kind}>{note}</Notice> : null}
            <Button type="submit" disabled={busy || !onRequest}>
              {tr("Request documents")}
            </Button>
            {!onRequest ? <p className="mt-2 text-xs text-[color:var(--fb-v2-text-muted)]">{tr("Preview: the form works on the public page.")}</p> : null}
          </form>
        </section>
      ) : null}

      <footer className="text-xs text-[color:var(--fb-v2-text-faint)]">{data.updated_at ? tr("Updated {date}", { date: data.updated_at.slice(0, 10) }) : null}</footer>
    </div>
  );
}
