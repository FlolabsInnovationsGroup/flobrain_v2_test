"use client";

import { useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Badge, Field, Notice, Row, Rows, Section, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, errorText } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";

import { inputClass } from "./bits";
import { cleanSubprocessors, emptyDocument, emptySubprocessor, removeAt, toggle, updateAt } from "./logic";
import { TrustView } from "./TrustView";
import type { TrustRequest, TrustSection, TrustSettings } from "./types";

const ORDER: TrustSection[] = ["overview", "controls", "subprocessors", "data_location", "documents"];

function SectionName({ s }: { s: TrustSection }) {
  const tr = useTr();
  if (s === "overview") return <>{tr("Security overview")}</>;
  if (s === "controls") return <>{tr("Control readiness")}</>;
  if (s === "subprocessors") return <>{tr("Subprocessors")}</>;
  if (s === "data_location") return <>{tr("Where your data is stored")}</>;
  return <>{tr("Documents on request")}</>;
}

function Requests({ orgId, canManage }: { orgId: string; canManage: boolean }) {
  const tr = useTr();
  const list = useOrgData<TrustRequest[]>(orgId, "/compliance/trust/requests");
  const [error, setError] = useState<string | null>(null);
  const rows = list.data ?? [];
  async function mark(id: string, status: TrustRequest["status"]) {
    setError(null);
    try {
      await api.patch(`/orgs/${orgId}/compliance/trust/requests/${id}`, { status });
      list.reload();
    } catch (err) {
      setError(errorText(err));
    }
  }
  return (
    <Section title={tr("Document requests")}>
      {error ? <Notice kind="error">{error}</Notice> : null}
      <ScreenBody state={list.state === "ready" && !rows.length ? "empty" : list.state} error={list.error} emptyLabel={tr("No requests yet.")} onRetry={list.reload}>
        <Rows>
          {rows.map((r) => (
            <Row key={r.id}>
              <div className="min-w-0 flex-1 basis-64">
                <p className="font-medium" dir="auto">
                  {r.name} {r.company ? <span className="font-normal text-[color:var(--fb-v2-text-muted)]">· {r.company}</span> : null}
                </p>
                <p className="text-xs text-[color:var(--fb-v2-text-muted)]">
                  <span dir="ltr">{r.email}</span> · {when(r.created_at)} · {r.documents.join(", ") || tr("No documents picked")}
                </p>
                {r.message ? (
                  <p className="text-sm" dir="auto">
                    {r.message}
                  </p>
                ) : null}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {r.status === "new" ? <Badge>{tr("New")}</Badge> : r.status === "sent" ? <Badge tone="good">{tr("Sent")}</Badge> : <Badge>{tr("Declined")}</Badge>}
                {canManage && r.status === "new" ? (
                  <>
                    <Button variant="outline" onClick={() => mark(r.id, "sent")}>
                      {tr("Mark sent")}
                    </Button>
                    <Button variant="ghost" onClick={() => mark(r.id, "declined")}>
                      {tr("Decline")}
                    </Button>
                  </>
                ) : null}
              </div>
            </Row>
          ))}
        </Rows>
      </ScreenBody>
    </Section>
  );
}

export function TrustEditor({ orgId, canManage }: { orgId: string; canManage: boolean }) {
  const tr = useTr();
  const { data, state, error, reload, setData } = useOrgData<TrustSettings>(orgId, "/compliance/trust");
  const [edit, setDraft] = useState<TrustSettings | null>(null);
  const draft = edit ?? data;
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState(false);

  async function save(extra: Partial<TrustSettings> = {}) {
    if (!draft) return;
    setBusy(true);
    setMessage(null);
    const body = {
      slug: draft.slug,
      sections: draft.sections,
      headline: draft.headline,
      overview: draft.overview,
      subprocessors: cleanSubprocessors(draft.subprocessors),
      data_location: draft.data_location,
      documents: draft.documents.filter((d) => d.title.trim()),
      contact_email: draft.contact_email,
      ...extra,
    };
    try {
      const next = await api.put<TrustSettings>(`/orgs/${orgId}/compliance/trust`, body);
      setData((prev) => (prev ? { ...prev, ...next } : next));
      setDraft(null);
      setMessage({
        kind: "ok",
        text: "published" in extra ? (extra.published ? tr("Published. Anyone with the link can see it.") : tr("Unpublished. The page is offline.")) : tr("Saved."),
      });
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    } finally {
      setBusy(false);
    }
  }

  function applyExample() {
    if (!draft?.example) return;
    const ex = draft.example;
    setDraft({ ...draft, headline: ex.headline, overview: ex.overview, subprocessors: ex.subprocessors, data_location: ex.data_location, documents: ex.documents, sections: ex.sections });
  }

  const url = typeof window !== "undefined" && draft ? `${window.location.origin}/trust/${draft.slug}` : "";
  const ro = !canManage;

  return (
    <ScreenBody state={state} error={error} onRetry={reload}>
      {draft ? (
        <>
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
            <div className="min-w-0">
              <p className="font-medium">
                {draft.published ? <Badge tone="good">{tr("Published")}</Badge> : <Badge>{tr("Not published")}</Badge>}
                <span className="ms-2 text-sm text-[color:var(--fb-v2-text-muted)]">
                  {draft.published && draft.published_at ? tr("Since {when}", { when: when(draft.published_at) }) : tr("Only people in this workspace can see the preview.")}
                </span>
              </p>
              {draft.published ? (
                <a className="v2-mono break-all text-sm text-[color:var(--fb-v2-accent)] underline underline-offset-2" href={`/trust/${draft.slug}`} target="_blank" rel="noopener noreferrer" dir="ltr">
                  {url || `/trust/${draft.slug}`}
                </a>
              ) : null}
            </div>
            <div className="flex flex-wrap gap-2">
              <Button variant="ghost" aria-expanded={preview} onClick={() => setPreview((v) => !v)}>
                {preview ? tr("Hide preview") : tr("Preview")}
              </Button>
              {canManage ? (
                draft.published ? (
                  <Button variant="outline" disabled={busy} onClick={() => save({ published: false })}>
                    {tr("Unpublish")}
                  </Button>
                ) : (
                  <Button disabled={busy} onClick={() => save({ published: true })}>
                    {tr("Save and publish")}
                  </Button>
                )
              ) : null}
            </div>
          </div>
          {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}

          {preview && data ? (
            <div className="mb-8 rounded-xl border border-[color:var(--fb-v2-border)] p-4 sm:p-6">
              <TrustView data={data.preview} />
              <p className="mt-4 text-xs text-[color:var(--fb-v2-text-muted)]">{tr("The preview shows what was last saved.")}</p>
            </div>
          ) : null}

          <form
            onSubmit={(e) => {
              e.preventDefault();
              save();
            }}
          >
            <fieldset disabled={ro} className="space-y-2">
              <Section
                title={tr("Page")}
                aside={
                  canManage && draft.example ? (
                    <Button type="button" variant="ghost" onClick={applyExample}>
                      {tr("Start from FloBrain's example")}
                    </Button>
                  ) : null
                }
              >
                <div className="grid gap-x-4 sm:grid-cols-2">
                  <Field label={tr("Address")} hint={tr("Lowercase letters, numbers and hyphens.")}>
                    <div className="flex items-center gap-1" dir="ltr">
                      <span className="v2-mono text-sm text-[color:var(--fb-v2-text-muted)]">/trust/</span>
                      <input className={inputClass} value={draft.slug} onChange={(e) => setDraft({ ...draft, slug: e.target.value.toLowerCase() })} />
                    </div>
                  </Field>
                  <Field label={tr("Contact email for requests (not shown on the page)")}>
                    <input className={inputClass} type="email" dir="ltr" value={draft.contact_email} onChange={(e) => setDraft({ ...draft, contact_email: e.target.value })} />
                  </Field>
                </div>
                <Field label={tr("Headline")}>
                  <input className={inputClass} dir="auto" maxLength={160} value={draft.headline} onChange={(e) => setDraft({ ...draft, headline: e.target.value })} />
                </Field>
                <fieldset className="mb-4">
                  <legend className="mb-1 text-sm font-medium">{tr("Sections to show")}</legend>
                  <div className="flex flex-wrap gap-x-4 gap-y-2 text-sm">
                    {ORDER.map((s) => (
                      <label key={s} className="flex items-center gap-1.5">
                        <input type="checkbox" checked={draft.sections.includes(s)} onChange={() => setDraft({ ...draft, sections: toggle(draft.sections, s, ORDER) })} />
                        <SectionName s={s} />
                      </label>
                    ))}
                  </div>
                  <p className="mt-1 text-xs text-[color:var(--fb-v2-text-muted)]">{tr("Control readiness shows only percentages by area: no control names, evidence or people.")}</p>
                </fieldset>
              </Section>

              <Section title={tr("Security overview")}>
                <textarea className={`${inputClass} min-h-32`} dir="auto" maxLength={4000} aria-label={tr("Security overview")} value={draft.overview} onChange={(e) => setDraft({ ...draft, overview: e.target.value })} />
              </Section>

              <Section
                title={tr("Subprocessors")}
                aside={
                  canManage ? (
                    <Button type="button" variant="ghost" onClick={() => setDraft({ ...draft, subprocessors: [...draft.subprocessors, emptySubprocessor()] })}>
                      {tr("Add a subprocessor")}
                    </Button>
                  ) : null
                }
              >
                <ul className="space-y-3">
                  {draft.subprocessors.map((s, i) => (
                    <li key={i} className="grid gap-2 rounded-xl bg-[color:var(--fb-v2-surface)] p-3 sm:grid-cols-[1fr_1.5fr_1fr_1fr_auto] sm:items-end">
                      <label className="text-xs">
                        <span className="mb-1 block text-[color:var(--fb-v2-text-muted)]">{tr("Company")}</span>
                        <input className={inputClass} dir="auto" value={s.name} onChange={(e) => setDraft({ ...draft, subprocessors: updateAt(draft.subprocessors, i, { name: e.target.value }) })} />
                      </label>
                      <label className="text-xs">
                        <span className="mb-1 block text-[color:var(--fb-v2-text-muted)]">{tr("What they do for us")}</span>
                        <input className={inputClass} dir="auto" value={s.purpose} onChange={(e) => setDraft({ ...draft, subprocessors: updateAt(draft.subprocessors, i, { purpose: e.target.value }) })} />
                      </label>
                      <label className="text-xs">
                        <span className="mb-1 block text-[color:var(--fb-v2-text-muted)]">{tr("Location")}</span>
                        <input className={inputClass} dir="auto" value={s.location} onChange={(e) => setDraft({ ...draft, subprocessors: updateAt(draft.subprocessors, i, { location: e.target.value }) })} />
                      </label>
                      <label className="text-xs">
                        <span className="mb-1 block text-[color:var(--fb-v2-text-muted)]">{tr("Website (https)")}</span>
                        <input className={inputClass} dir="ltr" value={s.website} onChange={(e) => setDraft({ ...draft, subprocessors: updateAt(draft.subprocessors, i, { website: e.target.value }) })} />
                      </label>
                      {canManage ? (
                        <Button type="button" variant="ghost" aria-label={tr("Remove {name}", { name: s.name || tr("this row") })} onClick={() => setDraft({ ...draft, subprocessors: removeAt(draft.subprocessors, i) })}>
                          {tr("Remove")}
                        </Button>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </Section>

              <Section title={tr("Where your data is stored")}>
                <input className={inputClass} dir="auto" maxLength={300} aria-label={tr("Where your data is stored")} value={draft.data_location} onChange={(e) => setDraft({ ...draft, data_location: e.target.value })} />
              </Section>

              <Section
                title={tr("Documents on request")}
                aside={
                  canManage ? (
                    <Button type="button" variant="ghost" onClick={() => setDraft({ ...draft, documents: [...draft.documents, emptyDocument()] })}>
                      {tr("Add a document")}
                    </Button>
                  ) : null
                }
              >
                <p className="mb-2 text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Visitors pick documents and leave their email. Admins get a notification and an email; nothing is sent automatically.")}</p>
                <ul className="space-y-3">
                  {draft.documents.map((d, i) => (
                    <li key={i} className="grid gap-2 rounded-xl bg-[color:var(--fb-v2-surface)] p-3 sm:grid-cols-[1fr_2fr_auto] sm:items-end">
                      <label className="text-xs">
                        <span className="mb-1 block text-[color:var(--fb-v2-text-muted)]">{tr("Title")}</span>
                        <input className={inputClass} dir="auto" value={d.title} onChange={(e) => setDraft({ ...draft, documents: updateAt(draft.documents, i, { title: e.target.value }) })} />
                      </label>
                      <label className="text-xs">
                        <span className="mb-1 block text-[color:var(--fb-v2-text-muted)]">{tr("Description")}</span>
                        <input className={inputClass} dir="auto" value={d.description} onChange={(e) => setDraft({ ...draft, documents: updateAt(draft.documents, i, { description: e.target.value }) })} />
                      </label>
                      {canManage ? (
                        <Button type="button" variant="ghost" onClick={() => setDraft({ ...draft, documents: removeAt(draft.documents, i) })}>
                          {tr("Remove")}
                        </Button>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </Section>
              {canManage ? (
                <Button type="submit" disabled={busy}>
                  {tr("Save")}
                </Button>
              ) : null}
            </fieldset>
          </form>
          <div className="mt-8">
            <Requests orgId={orgId} canManage={canManage} />
          </div>
        </>
      ) : null}
    </ScreenBody>
  );
}
