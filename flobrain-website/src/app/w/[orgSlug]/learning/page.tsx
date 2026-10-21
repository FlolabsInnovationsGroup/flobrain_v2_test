"use client";

import { useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { Button } from "@/components/v2/ui/button";
import { Badge, Field, Notice, PageHeader, Row, Rows, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { has } from "@/lib/v2/access";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText, rowsOf } from "@/lib/v2/api";
import { useOrgData } from "@/lib/v2/useOrgData";
import { cn } from "@/lib/utils";

type Path = { id: string; name: string; description: string; steps: { kind: string; title: string; ref: string }[]; done_steps: number[]; completed_at: string | null };
type Quiz = { id: string; title: string; status: string; pass_mark: number; ai_drafted: boolean; questions: { question: string; options: string[]; answer?: number }[] };
type Cert = { id: string; user: string; kind: string; data: Record<string, unknown>; public_slug: string; issued_at: string; revoked: boolean };
type Item = { id: string; kind: string; title: string; summary: string; is_public: boolean };
type Mentorship = { id: string; mentor: { id: string; name: string }; mentee: { id: string; name: string }; cadence: string };
type Note = { id: string; author: string | null; body: string; created_at: string };
type Progress = { paths: { name: string; done: number; total: number; completed: boolean }[]; quizzes: { title: string; score: number; passed: boolean; at: string }[] };
type Cohort = { id: string; name: string; starts_on: string; members: number; instructor: boolean; instructors: string[]; is_member: boolean; can_view_progress: boolean };
type CohortProgress = { id: string; name: string; members: ({ id: string; name: string } & Progress)[] };
type Masterclass = { id: string; title: string; url: string; status: string; updated_at: string; for_you: boolean; audience?: string[] };
type Masterclasses = {
  configured: boolean;
  can_connect: boolean;
  in_room?: boolean;
  audience_property?: string;
  last_sync_at?: string | null;
  demo?: boolean;
  items: Masterclass[];
};

const TABS = ["Paths", "Quizzes", "Masterclasses", "Cohorts", "Certificates", "Portfolio", "Mentorship"] as const;

function ProgressSummary({ progress }: { progress: Progress }) {
  const tr = useTr();
  const passed = progress.quizzes.filter((q) => q.passed).length;
  return (
    <div className="text-sm">
      {progress.paths.length ? (
        <ul className="space-y-1">
          {progress.paths.map((p) => (
            <li key={p.name} className="flex flex-wrap items-center gap-2">
              <span>{p.name}</span>
              {p.completed ? <Badge tone="good">{tr("Completed")}</Badge> : <Badge>{tr("{done} of {total}", { done: p.done, total: p.total })}</Badge>}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-[color:var(--fb-v2-text-muted)]">{tr("No learning path started yet.")}</p>
      )}
      <p className="mt-1 text-[color:var(--fb-v2-text-muted)]">
        {progress.quizzes.length ? tr("Quizzes: {passed} passed of {n} attempts.", { passed, n: progress.quizzes.length }) : tr("No quiz attempts yet.")}
      </p>
    </div>
  );
}

function QuizRunner({ orgId, quiz, onDone }: { orgId: string; quiz: Quiz; onDone: (text: string) => void }) {
  const tr = useTr();
  const [answers, setAnswers] = useState<number[]>(quiz.questions.map(() => -1));
  return (
    <form
      className="mt-3 space-y-4"
      onSubmit={async (e) => {
        e.preventDefault();
        try {
          const r = await api.post<{ score?: number; passed: boolean; right?: number; total?: number }>(`/orgs/${orgId}/learning/quizzes/${quiz.id}/attempts`, { answers });
          onDone(r.passed
              ? tr("{right} of {total} right ({score}%). Passed.", { right: r.right ?? 0, total: r.total ?? 0, score: r.score ?? 0 })
              : tr("Not passed yet. You need {mark}% to pass. You can try 5 times a day.", { mark: quiz.pass_mark }),
          );
        } catch (err) {
          onDone(errorText(err));
        }
      }}
    >
      {quiz.questions.map((q, i) => (
        <fieldset key={i}>
          <legend className="mb-1 font-medium">
            {i + 1}. {q.question}
          </legend>
          {q.options.map((o, j) => (
            <label key={j} className="block text-sm">
              <input type="radio" name={`q${i}`} checked={answers[i] === j} onChange={() => setAnswers(answers.map((a, k) => (k === i ? j : a)))} /> {o}
            </label>
          ))}
        </fieldset>
      ))}
      <Button type="submit" disabled={answers.includes(-1)}>
        {tr("Submit answers")}
      </Button>
    </form>
  );
}

export default function LearningPage() {
  const { orgId, access } = useAccess();
  const tr = useTr();
  const manager = has(access, "learning.manage");
  const issuer = has(access, "certificates.issue");
  const [tab, setTab] = useState<(typeof TABS)[number]>("Paths");
  const paths = useOrgData<Path[]>(orgId, tab === "Paths" ? "/learning/paths" : null, { list: true });
  const quizzes = useOrgData<Quiz[]>(orgId, tab === "Quizzes" ? "/learning/quizzes" : null, { list: true });
  const certs = useOrgData<Cert[]>(orgId, tab === "Certificates" ? "/certificates" : null, { list: true });
  const portfolio = useOrgData<{ slug: string | null; items: Item[] }>(orgId, tab === "Portfolio" ? "/portfolio" : null);
  const pairs = useOrgData<Mentorship[]>(orgId, tab === "Mentorship" ? "/mentorships" : null, { list: true });
  const cohorts = useOrgData<Cohort[]>(orgId, tab === "Cohorts" ? "/cohorts" : null, { list: true });
  const classes = useOrgData<Masterclasses>(orgId, tab === "Masterclasses" ? "/learning/masterclasses" : null);
  const [cohortOpen, setCohortOpen] = useState<CohortProgress | null>(null);
  const [menteeFor, setMenteeFor] = useState<{ id: string; progress: Progress } | null>(null);
  const members = useOrgData<{ results: { id: string; username: string }[] }>(orgId, issuer || manager ? "/members" : null);
  const docs = useOrgData<{ results?: { id: string; title: string }[] }>(orgId, manager && tab === "Quizzes" ? "/docs/search?q=" : null);
  const [taking, setTaking] = useState<string | null>(null);
  const [notesFor, setNotesFor] = useState<string | null>(null);
  const [notes, setNotes] = useState<Note[]>([]);
  const [note, setNote] = useState("");
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [form, setForm] = useState({ pathName: "", stepTitle: "", stepUrl: "", issueUser: "", issueDetails: false, mentor: "", mentee: "", doc: "", item: "" });

  async function act<T>(fn: () => Promise<T>, ok: string, after?: (v: T) => void) {
    setMessage(null);
    try {
      const v = await fn();
      setMessage({ kind: "ok", text: ok });
      after?.(v);
    } catch (err) {
      setMessage({ kind: "error", text: errorText(err) });
    }
  }

  const people = rowsOf<{ id: string; username: string }>(members.data);

  return (
    <div className="max-w-5xl">
      <PageHeader title={tr("Learning")} intro={tr("Learning paths, quizzes, masterclasses, cohorts, certificates from your real work, your portfolio, and mentoring.")} />
      <div role="tablist" className="mb-6 flex flex-wrap gap-1 border-b border-[color:var(--fb-v2-border)]">
        {TABS.map((name) => (
          <button
            key={name}
            role="tab"
            aria-selected={tab === name}
            onClick={() => setTab(name)}
            className={cn(
              "-mb-px border-b-2 px-3 py-2 text-sm",
              tab === name ? "border-[color:var(--fb-v2-accent)] font-medium" : "border-transparent text-[color:var(--fb-v2-text-muted)]",
            )}
          >
            {tr(name)}
          </button>
        ))}
      </div>
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}

      {tab === "Paths" ? (
        <>
          {manager ? (
            <form
              className="mb-6 grid gap-x-3 rounded-xl bg-[color:var(--fb-v2-surface)] p-4 sm:grid-cols-3"
              onSubmit={(e) => {
                e.preventDefault();
                act(
                  () => api.post(`/orgs/${orgId}/learning/paths`, { name: form.pathName, steps: [{ kind: "link", title: form.stepTitle, ref: form.stepUrl }] }),
                  tr("Path created."),
                  paths.reload,
                );
              }}
            >
              <Field label={tr("New path")}>
                <input className="v2-input" required value={form.pathName} onChange={(e) => setForm({ ...form, pathName: e.target.value })} />
              </Field>
              <Field label={tr("First step")}>
                <input className="v2-input" required value={form.stepTitle} onChange={(e) => setForm({ ...form, stepTitle: e.target.value })} />
              </Field>
              <Field label={tr("Link (https)")}>
                <input className="v2-input" type="url" required value={form.stepUrl} onChange={(e) => setForm({ ...form, stepUrl: e.target.value })} />
              </Field>
              <div>
                <Button type="submit">{tr("Create path")}</Button>
              </div>
            </form>
          ) : null}
          <ScreenBody state={paths.state} error={paths.error} emptyLabel={tr("No learning paths yet.")} onRetry={paths.reload}>
            <div className="space-y-4">
              {rowsOf<Path>(paths.data).map((p) => (
                <section key={p.id} className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
                  <div className="flex items-center justify-between gap-2">
                    <h2 className="font-semibold">{p.name}</h2>
                    {p.completed_at ? <Badge tone="good">{tr("Completed")}</Badge> : <Badge>{tr("{done} of {total}", { done: p.done_steps.length, total: p.steps.length })}</Badge>}
                  </div>
                  {p.description ? <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{p.description}</p> : null}
                  <ol className="mt-3 space-y-2">
                    {p.steps.map((s, i) => (
                      <li key={i} className="flex items-center gap-3 text-sm">
                        <input
                          type="checkbox"
                          aria-label={tr("Mark {title} done", { title: s.title })}
                          checked={p.done_steps.includes(i)}
                          onChange={(e) => act(() => api.post(`/orgs/${orgId}/learning/paths/${p.id}/progress`, { step: i, done: e.target.checked }), tr("Saved."), paths.reload)}
                        />
                        {s.kind === "link" ? (
                          <a className="hover:underline" href={s.ref} target="_blank" rel="noreferrer noopener">
                            {s.title}
                          </a>
                        ) : (
                          <span>{s.title}</span>
                        )}
                      </li>
                    ))}
                  </ol>
                </section>
              ))}
            </div>
          </ScreenBody>
        </>
      ) : null}

      {tab === "Quizzes" ? (
        <>
          {manager ? (
            <form
              className="mb-6 flex flex-wrap items-end gap-2 rounded-xl bg-[color:var(--fb-v2-surface)] p-4"
              onSubmit={(e) => {
                e.preventDefault();
                act(() => api.post(`/orgs/${orgId}/learning/quizzes/draft`, { document: form.doc }), tr("Draft ready. Review it, then publish."), quizzes.reload);
              }}
            >
              <label className="text-sm">
                <span className="mb-1 block font-medium">{tr("Draft a quiz from a document (AI)")}</span>
                <select className="v2-input w-72" required value={form.doc} onChange={(e) => setForm({ ...form, doc: e.target.value })}>
                  <option value="">{tr("Choose a document")}</option>
                  {rowsOf<{ id: string; title: string }>(docs.data).map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.title}
                    </option>
                  ))}
                </select>
              </label>
              <Button type="submit" variant="outline">
                {tr("Draft quiz")}
              </Button>
            </form>
          ) : null}
          <ScreenBody state={quizzes.state} error={quizzes.error} emptyLabel={tr("No quizzes yet.")} onRetry={quizzes.reload}>
            <Rows>
              {rowsOf<Quiz>(quizzes.data).map((q) => (
                <Row key={q.id} className="items-start">
                  <div className="min-w-0 flex-1">
                    <p className="font-medium">
                      {q.title} {q.ai_drafted ? <Badge>{tr("AI draft")}</Badge> : null}
                    </p>
                    <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
                      {tr("{n} questions. Pass mark {mark}%.", { n: q.questions.length, mark: q.pass_mark })}
                    </p>
                    {manager && q.status === "draft" ? (
                      <ol className="mt-2 list-decimal ps-5 text-sm">
                        {q.questions.map((x, i) => (
                          <li key={i}>
                            {x.question} <span className="text-[color:var(--fb-v2-text-muted)]">{tr("Answer: {answer}", { answer: x.options[x.answer ?? 0] })}</span>
                          </li>
                        ))}
                      </ol>
                    ) : null}
                    {taking === q.id && orgId ? (
                      <QuizRunner
                        orgId={orgId}
                        quiz={q}
                        onDone={(text) => {
                          setMessage({ kind: "ok", text });
                          setTaking(null);
                        }}
                      />
                    ) : null}
                  </div>
                  {manager && q.status === "draft" ? (
                    <Button variant="waiting" onClick={() => act(() => api.patch(`/orgs/${orgId}/learning/quizzes/${q.id}`, { status: "published" }), tr("Published."), quizzes.reload)}>
                      {tr("Publish")}
                    </Button>
                  ) : q.status === "published" && taking !== q.id ? (
                    <Button variant="outline" onClick={() => setTaking(q.id)}>
                      {tr("Take quiz")}
                    </Button>
                  ) : null}
                </Row>
              ))}
            </Rows>
          </ScreenBody>
        </>
      ) : null}

      {tab === "Certificates" ? (
        <>
          {issuer ? (
            <form
              className="mb-6 flex flex-wrap items-end gap-2 rounded-xl bg-[color:var(--fb-v2-surface)] p-4"
              onSubmit={(e) => {
                e.preventDefault();
                act(() => api.post(`/orgs/${orgId}/certificates`, { user: form.issueUser, kind: "internship_completion", include_details: form.issueDetails }), tr("Certificate issued and signed."), certs.reload);
              }}
            >
              <label className="text-sm">
                <span className="mb-1 block font-medium">{tr("Issue an internship certificate to")}</span>
                <select className="v2-input w-64" required value={form.issueUser} onChange={(e) => setForm({ ...form, issueUser: e.target.value })}>
                  <option value="">{tr("Choose a person")}</option>
                  {people.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.username}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={form.issueDetails} onChange={(e) => setForm({ ...form, issueDetails: e.target.checked })} />
                {tr("Show project and category names")}
              </label>
              <Button type="submit">{tr("Issue")}</Button>
              <p className="w-full text-xs text-[color:var(--fb-v2-text-muted)]">
                {tr(
                  "Built from their time, tasks and projects in FloBrain. Names of internal projects appear on the public page only if you tick the box. It can be revoked later.",
                )}
              </p>
            </form>
          ) : null}
          <ScreenBody state={certs.state} error={certs.error} emptyLabel={tr("No certificates yet.")} onRetry={certs.reload}>
            <Rows>
              {rowsOf<Cert>(certs.data).map((c) => (
                <Row key={c.id}>
                  <div>
                    <p className="font-medium">
                      {String(c.data.recipient)}: {tr(c.kind === "internship_completion" ? "Internship completion" : "Learning path")}
                    </p>
                    <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
                      {tr("{hours} h, {tasks} tasks. Issued {when}.", { hours: String(c.data.hours_total), tasks: String(c.data.tasks_completed), when: when(c.issued_at) })}
                    </p>
                  </div>
                  <div className="flex gap-2">
                    {c.revoked ? <Badge tone="bad">{tr("Revoked")}</Badge> : <a className="text-sm underline" href={`/verify/${c.public_slug}`} target="_blank" rel="noreferrer">{tr("Public page")}</a>}
                    {issuer && !c.revoked ? (
                      <Button variant="danger" onClick={() => act(() => api.post(`/orgs/${orgId}/certificates/${c.id}/revoke`), tr("Revoked."), certs.reload)}>
                        {tr("Revoke")}
                      </Button>
                    ) : null}
                  </div>
                </Row>
              ))}
            </Rows>
          </ScreenBody>
        </>
      ) : null}

      {tab === "Portfolio" ? (
        <>
          <form
            className="mb-6 flex flex-wrap items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              act(() => api.post(`/orgs/${orgId}/portfolio`, { kind: "project", title: form.item }), tr("Added. It stays private until you publish it."), portfolio.reload);
            }}
          >
            <label className="text-sm">
              <span className="mb-1 block font-medium">{tr("Add a project to your portfolio")}</span>
              <input className="v2-input w-72" required value={form.item} onChange={(e) => setForm({ ...form, item: e.target.value })} />
            </label>
            <Button type="submit" variant="outline">
              {tr("Add")}
            </Button>
          </form>
          {portfolio.data?.slug ? (
            <p className="mb-3 text-sm">
              {tr("Your public page:")} <a className="underline" href={`/p/${portfolio.data.slug}`} target="_blank" rel="noreferrer">/p/{portfolio.data.slug}</a>
            </p>
          ) : null}
          <ScreenBody state={portfolio.state} error={portfolio.error} onRetry={portfolio.reload}>
            <Rows>
              {(portfolio.data?.items ?? []).map((i) => (
                <Row key={i.id}>
                  <span>{i.title}</span>
                  <label className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={i.is_public} onChange={(e) => act(() => api.patch(`/orgs/${orgId}/portfolio/${i.id}`, { is_public: e.target.checked }), tr(e.target.checked ? "Public." : "Private."), portfolio.reload)} />
                    {tr("Public")}
                  </label>
                </Row>
              ))}
            </Rows>
          </ScreenBody>
        </>
      ) : null}

      {tab === "Mentorship" ? (
        <>
          {manager ? (
            <form
              className="mb-6 flex flex-wrap items-end gap-2 rounded-xl bg-[color:var(--fb-v2-surface)] p-4"
              onSubmit={(e) => {
                e.preventDefault();
                act(() => api.post(`/orgs/${orgId}/mentorships`, { mentor: form.mentor, mentee: form.mentee }), tr("Pair created."), pairs.reload);
              }}
            >
              {(["mentor", "mentee"] as const).map((key) => (
                <label key={key} className="text-sm">
                  <span className="mb-1 block font-medium ">{tr(key === "mentor" ? "Mentor" : "Mentee")}</span>
                  <select className="v2-input w-56" required value={form[key]} onChange={(e) => setForm({ ...form, [key]: e.target.value })}>
                    <option value="">{tr("Choose")}</option>
                    {people.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.username}
                      </option>
                    ))}
                  </select>
                </label>
              ))}
              <Button type="submit">{tr("Pair them")}</Button>
            </form>
          ) : null}
          <ScreenBody state={pairs.state} error={pairs.error} emptyLabel={tr("No mentorships yet.")} onRetry={pairs.reload}>
            <Rows>
              {rowsOf<Mentorship>(pairs.data).map((m) => {
                const mine = access?.user_id === m.mentor.id || access?.user_id === m.mentee.id;
                return (
                  <Row key={m.id} className="items-start">
                    <div className="min-w-0 flex-1">
                      <p className="font-medium">
                        {tr("{mentor} mentors {mentee}", { mentor: m.mentor.name, mentee: m.mentee.name })}
                      </p>
                      <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
                        {tr("Meets {cadence}. Notes are private to the two of them.", { cadence: tr(m.cadence) })}
                      </p>
                      {menteeFor?.id === m.id ? (
                        <div className="mt-3 rounded-lg bg-[color:var(--fb-v2-border)] p-3">
                          <p className="mb-1 text-sm font-medium">{tr("{name}'s learning progress", { name: m.mentee.name })}</p>
                          <ProgressSummary progress={menteeFor.progress} />
                        </div>
                      ) : null}
                      {notesFor === m.id ? (
                        <div className="mt-3 space-y-2">
                          {notes.map((n) => (
                            <p key={n.id} className="rounded-lg bg-[color:var(--fb-v2-border)] p-2 text-sm">
                              {n.body}
                            </p>
                          ))}
                          <form
                            className="flex gap-2"
                            onSubmit={(e) => {
                              e.preventDefault();
                              act(() => api.post<Note>(`/orgs/${orgId}/mentorships/${m.id}/notes`, { body: note }), tr("Note added."), (n) => {
                                setNotes([...notes, n]);
                                setNote("");
                              });
                            }}
                          >
                            <input className="v2-input" value={note} onChange={(e) => setNote(e.target.value)} placeholder={tr("Add a note for the two of you")} />
                            <Button type="submit">{tr("Add")}</Button>
                          </form>
                        </div>
                      ) : null}
                    </div>
                    <div className="flex gap-2">
                      {access?.user_id === m.mentor.id ? (
                        <Button
                          variant="outline"
                          onClick={() =>
                            act(
                              () => api.get<Progress>(`/orgs/${orgId}/mentorships/${m.id}/progress`),
                              tr("Progress loaded."),
                              (progress) => setMenteeFor({ id: m.id, progress }),
                            )
                          }
                        >
                          {tr("Mentee progress")}
                        </Button>
                      ) : null}
                      {mine ? (
                        <Button
                          variant="outline"
                          onClick={async () => {
                            setNotesFor(m.id);
                            setNotes(rowsOf<Note>(await api.get(`/orgs/${orgId}/mentorships/${m.id}/notes`)));
                          }}
                        >
                          {tr("Notes")}
                        </Button>
                      ) : null}
                    </div>
                  </Row>
                );
              })}
            </Rows>
          </ScreenBody>
        </>
      ) : null}

      {tab === "Masterclasses" ? (
        <ScreenBody state={classes.state} error={classes.error} onRetry={classes.reload}>
          {classes.data && !classes.data.configured ? (
            <Notice>
              {classes.data.can_connect
                ? tr("No masterclass database is connected yet. Connect Notion in Integrations with an internal integration token and the database id.")
                : tr("Masterclasses appear here once an admin connects your organization's Notion masterclass database.")}{" "}
              {classes.data.can_connect && access?.org.slug ? (
                <a className="underline" href={`/w/${access.org.slug}/integrations`}>
                  {tr("Open Integrations")}
                </a>
              ) : null}
            </Notice>
          ) : classes.data ? (
            <>
              <p className="mb-3 flex flex-wrap items-center gap-2 text-sm text-[color:var(--fb-v2-text-muted)]">
                {classes.data.demo ? <Badge tone="waiting">{tr("Demo")}</Badge> : null}
                {classes.data.audience_property && !manager
                  ? tr("From Notion, for your teams ({property}).", { property: classes.data.audience_property })
                  : tr("From Notion.")}{" "}
                {classes.data.last_sync_at ? tr("Synced {when}.", { when: when(classes.data.last_sync_at) }) : tr("Not synced yet.")}
              </p>
              {classes.data.in_room === false ? (
                <Notice>{tr("The masterclass database is shared with a room you're not in. Ask an admin to add you.")}</Notice>
              ) : classes.data.items.length ? (
                <Rows>
                  {classes.data.items.map((c) => (
                    <Row key={c.id}>
                      <div className="min-w-0">
                        {c.url ? (
                          <a className="font-medium hover:underline" href={c.url} target="_blank" rel="noopener noreferrer">
                            {c.title}
                          </a>
                        ) : (
                          <span className="font-medium">{c.title}</span>
                        )}
                        <p className="text-xs text-[color:var(--fb-v2-text-muted)]">
                          {tr("Updated {when}", { when: when(c.updated_at) })}
                          {manager && c.audience ? ` · ${c.audience.length ? tr("For {audience}", { audience: c.audience.join(", ") }) : tr("For everyone")}` : ""}
                        </p>
                      </div>
                      <div className="flex items-center gap-2">
                        {manager && !c.for_you ? <Badge>{tr("Not for your teams")}</Badge> : null}
                        {c.status ? <Badge tone={c.status.toLowerCase() === "published" ? "good" : "neutral"}>{c.status}</Badge> : null}
                      </div>
                    </Row>
                  ))}
                </Rows>
              ) : (
                <Notice>{tr("No masterclasses for your teams yet.")}</Notice>
              )}
            </>
          ) : null}
        </ScreenBody>
      ) : null}

      {tab === "Cohorts" ? (
        <ScreenBody state={cohorts.state} error={cohorts.error} emptyLabel={tr("You're not in a cohort yet.")} onRetry={cohorts.reload}>
          <Rows>
            {rowsOf<Cohort>(cohorts.data).map((c) => (
              <Row key={c.id} className="items-start">
                <div className="min-w-0 flex-1">
                  <p className="flex flex-wrap items-center gap-2 font-medium">
                    {c.name}
                    {c.instructor ? <Badge tone="accent">{tr("You teach")}</Badge> : c.is_member ? <Badge>{tr("Your cohort")}</Badge> : null}
                  </p>
                  <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
                    {tr("Started {date}. {n} members.", { date: c.starts_on, n: c.members })}{" "}
                    {c.instructors.length ? tr("Instructors: {names}.", { names: c.instructors.join(", ") }) : ""}
                  </p>
                  {cohortOpen?.id === c.id ? (
                    cohortOpen.members.length ? (
                      <ul className="mt-3 grid gap-3 sm:grid-cols-2">
                        {cohortOpen.members.map((m) => (
                          <li key={m.id} className="rounded-lg bg-[color:var(--fb-v2-border)] p-3">
                            <p className="mb-1 font-medium">{m.name}</p>
                            <ProgressSummary progress={m} />
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="mt-2 text-sm">{tr("No members to show.")}</p>
                    )
                  ) : null}
                </div>
                {c.can_view_progress ? (
                  cohortOpen?.id === c.id ? (
                    <Button variant="ghost" onClick={() => setCohortOpen(null)}>
                      {tr("Hide progress")}
                    </Button>
                  ) : (
                    <Button
                      variant="outline"
                      onClick={() => act(() => api.get<CohortProgress>(`/orgs/${orgId}/cohorts/${c.id}`), tr("Progress loaded."), setCohortOpen)}
                    >
                      {tr("View progress")}
                    </Button>
                  )
                ) : null}
              </Row>
            ))}
          </Rows>
          <p className="mt-2 text-xs text-[color:var(--fb-v2-text-muted)]">
            {tr("Instructors see everyone's progress. Team leads see the progress of their own team's members.")}
          </p>
        </ScreenBody>
      ) : null}
    </div>
  );
}
