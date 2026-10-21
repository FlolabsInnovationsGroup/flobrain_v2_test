"use client";

import { MessageSquareWarning, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Notice } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText } from "@/lib/v2/api";
import { browserLabel } from "@/lib/v2/screens/people";

const KINDS = [
  { value: "bug", label: "Something is broken" },
  { value: "idea", label: "An idea" },
  { value: "question", label: "A question" },
] as const;

/**
 * "Report a problem / Suggest" on every page (Phase 0). It sends the page path (no query string),
 * the browser name, and what the screen shows only if the person chooses to describe it.
 */
export function ReportProblem({ orgSlug }: { orgSlug: string }) {
  const tr = useTr();
  const { orgId } = useAccess();
  const pathname = usePathname() || "";
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState<(typeof KINDS)[number]["value"]>("bug");
  const [text, setText] = useState("");
  const [withScreen, setWithScreen] = useState(false);
  const [screen, setScreen] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState("");
  const browser = typeof navigator === "undefined" ? "" : browserLabel(navigator.userAgent);

  function reset() {
    setText("");
    setScreen("");
    setWithScreen(false);
    setError("");
  }

  async function send(e: React.FormEvent) {
    e.preventDefault();
    if (!orgId) return;
    setBusy(true);
    setError("");
    try {
      await api.post(`/orgs/${orgId}/feedback`, {
        kind,
        text,
        page: pathname,
        browser,
        ...(withScreen && screen.trim() ? { screenshot_note: screen.trim() } : {}),
      });
      reset();
      setSent(true);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button
        type="button"
        className="flex items-center gap-1.5 rounded-lg px-2 py-1 text-sm hover:bg-[color:var(--fb-v2-border)]"
        onClick={() => {
          setOpen(true);
          setSent(false);
        }}
      >
        <MessageSquareWarning size={16} aria-hidden />
        <span className="hidden md:inline">{tr("Report a problem")}</span>
        <span className="sr-only md:hidden">{tr("Report a problem")}</span>
      </button>
      {open ? (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 p-4 sm:items-center" role="dialog" aria-modal="true" aria-labelledby="report-title">
          <div className="w-full max-w-md rounded-xl bg-[color:var(--fb-v2-surface)] p-5 shadow-xl">
            <div className="mb-3 flex items-center justify-between">
              <h2 id="report-title" className="text-lg font-semibold">
                {tr("Report a problem or suggest something")}
              </h2>
              <button type="button" aria-label={tr("Close")} onClick={() => setOpen(false)}>
                <X size={18} />
              </button>
            </div>
            {sent ? (
              <>
                <Notice kind="ok">{tr("Thanks. The team reads every report.")}</Notice>
                <p className="mb-4 text-sm">
                  <Link className="hover:underline" href={`/w/${orgSlug}/settings/feedback`} onClick={() => setOpen(false)}>
                    {tr("See your reports")}
                  </Link>
                </p>
                <Button onClick={() => setOpen(false)}>{tr("Close")}</Button>
              </>
            ) : (
              <form onSubmit={send}>
                <fieldset className="mb-3 flex flex-wrap gap-2 text-sm">
                  <legend className="sr-only">{tr("What is it?")}</legend>
                  {KINDS.map((k) => (
                    <label key={k.value} className="inline-flex items-center gap-1.5 rounded-full px-3 py-1 ring-1 ring-inset ring-[color:var(--fb-v2-border)] has-[:checked]:ring-[color:var(--fb-v2-accent)]">
                      <input type="radio" name="kind" value={k.value} checked={kind === k.value} onChange={() => setKind(k.value)} />
                      {tr(k.label)}
                    </label>
                  ))}
                </fieldset>
                <label className="mb-3 block text-sm">
                  <span className="mb-1 block font-medium">{tr("What happened, or what would help?")}</span>
                  <textarea className="v2-input" rows={4} maxLength={4000} value={text} onChange={(e) => setText(e.target.value)} required autoFocus />
                </label>
                <label className="mb-2 flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={withScreen} onChange={(e) => setWithScreen(e.target.checked)} />
                  {tr("Describe what the screen shows")}
                </label>
                {withScreen ? (
                  <label className="mb-3 block text-sm">
                    <span className="sr-only">{tr("What the screen shows")}</span>
                    <textarea
                      className="v2-input"
                      rows={2}
                      maxLength={2000}
                      value={screen}
                      onChange={(e) => setScreen(e.target.value)}
                      placeholder={tr("For example: the Save button stays grey after I type a title")}
                    />
                  </label>
                ) : null}
                <p className="mb-3 text-xs text-[color:var(--fb-v2-text-muted)]">
                  {tr("We also send: the page {page} and your browser ({browser}). Nothing else from the screen.", { page: pathname, browser })}
                </p>
                {error ? <Notice kind="error">{error}</Notice> : null}
                <div className="flex gap-2">
                  <Button type="submit" disabled={busy || !text.trim()}>
                    {busy ? tr("Sending") : tr("Send")}
                  </Button>
                  <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
                    {tr("Cancel")}
                  </Button>
                </div>
              </form>
            )}
          </div>
        </div>
      ) : null}
    </>
  );
}
