"use client";

import { Play, Square } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Notice } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, apiError, errorText, rowsOf } from "@/lib/v2/api";
import { CATEGORIES, formatClock } from "@/lib/v2/screens/time";
import {
  applyTimerResponse,
  clockSkew,
  elapsedSeconds,
  emptyTimer,
  type RunningTimer,
} from "@/lib/v2/screens/timer";

/** Other parts of the page (the Time screen) listen for this to reload. */
export const TIMER_EVENT = "flobrain:timer-changed";

type Running = RunningTimer & { category: string; task: string | null };
type MyTask = { id: string; title: string; status: string };

export function TopBarTimer({ orgId }: { orgId?: string | null }) {
  const tr = useTr();
  const [snapshot, setSnapshot] = useState(emptyTimer());
  const [skew, setSkew] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ description: "", task: "", category: "projects" });
  const [tasks, setTasks] = useState<MyTask[]>([]);
  const [error, setError] = useState<string | null>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const running = snapshot.running as Running | null;

  const sync = useCallback(() => {
    if (!orgId) return;
    const asked = Date.now();
    api
      .get<{ running: Running | null; server_time?: string }>(`/orgs/${orgId}/timer`)
      .then((data) => {
        setSkew(clockSkew(data.server_time, (asked + Date.now()) / 2));
        setSnapshot((current) => (data.running ? applyTimerResponse(current, { type: "loaded", running: data.running }) : emptyTimer()));
      })
      .catch(() => undefined);
  }, [orgId]);

  useEffect(() => {
    sync();
    const poll = window.setInterval(sync, 30000);
    window.addEventListener(TIMER_EVENT, sync);
    window.addEventListener("focus", sync);
    return () => {
      window.clearInterval(poll);
      window.removeEventListener(TIMER_EVENT, sync);
      window.removeEventListener("focus", sync);
    };
  }, [sync]);

  useEffect(() => {
    if (!running) return;
    const tick = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(tick);
  }, [running]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && setOpen(false);
    const onClick = (event: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(event.target as Node)) setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onClick);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onClick);
    };
  }, [open]);

  function openForm() {
    setError(null);
    setForm(running ? { description: running.description, task: running.task ?? "", category: running.category || "projects" } : form);
    setOpen(true);
    if (orgId && tasks.length === 0) {
      api
        .get(`/orgs/${orgId}/tasks`, { filter: "mine", page_size: "100" })
        .then((data) => setTasks(rowsOf<MyTask>(data).filter((t) => t.status !== "done")))
        .catch(() => undefined);
    }
  }

  function changed() {
    window.dispatchEvent(new Event(TIMER_EVENT));
  }

  async function start() {
    if (!orgId) return;
    setError(null);
    try {
      const started = await api.post<Running>(`/orgs/${orgId}/timer/start`, {
        description: form.description.trim(),
        task: form.task || null,
        category: form.category,
      });
      setNow(Date.now());
      setSnapshot(applyTimerResponse(snapshot, { type: "started", running: started }));
      setOpen(false);
      setForm({ description: "", task: "", category: form.category });
      changed();
    } catch (err) {
      const e = apiError(err);
      if (e.status === 409) {
        const data = (err as { response?: { data?: { details?: Running } } }).response?.data?.details;
        setSnapshot(applyTimerResponse(snapshot, { type: "conflict", running: data ?? null }));
        setError(tr("Stop the current session first."));
        return;
      }
      setError(errorText(err));
    }
  }

  async function update() {
    if (!orgId) return;
    setError(null);
    try {
      const data = await api.patch<Running>(`/orgs/${orgId}/timer`, {
        description: form.description.trim(),
        task: form.task || null,
        category: form.category,
      });
      setSnapshot(applyTimerResponse(snapshot, { type: "loaded", running: data }));
      setOpen(false);
      changed();
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function stop() {
    if (!orgId) return;
    setError(null);
    try {
      await api.post(`/orgs/${orgId}/timer/stop`, {});
      setSnapshot(applyTimerResponse(snapshot, { type: "stopped" }));
      setOpen(false);
      changed();
    } catch (err) {
      setError(errorText(err));
      sync();
    }
  }

  const seconds = elapsedSeconds(running, now, skew);
  return (
    <div ref={boxRef} className="relative flex items-center gap-2">
      {running ? (
        <>
          <button
            type="button"
            className="max-w-48 truncate text-sm text-[color:var(--fb-v2-text-muted)] hover:underline"
            onClick={openForm}
            title={tr("Edit the running timer")}
          >
            {running.description || running.task_title || tr("Timer running")}
          </button>
          <span className="font-mono text-sm tabular-nums" aria-label={tr("Time on this session")} role="timer">
            {formatClock(seconds)}
          </span>
          <Button type="button" variant="outline" onClick={stop} aria-label={tr("Stop the timer")}>
            <Square aria-hidden className="me-1 size-3.5" />
            {tr("Stop")}
          </Button>
        </>
      ) : (
        <Button type="button" variant="ghost" onClick={openForm} disabled={!orgId}>
          <Play aria-hidden className="me-1 size-3.5" />
          {tr("Start timer")}
        </Button>
      )}
      {open ? (
        <div
          role="dialog"
          aria-label={running ? tr("Edit the running timer") : tr("Start a timer")}
          className="absolute end-0 top-full z-30 mt-2 w-80 rounded-xl bg-[color:var(--fb-v2-surface)] p-4 shadow-xl ring-1 ring-[color:var(--fb-v2-border)]"
        >
          {error ? <Notice kind="error">{error}</Notice> : null}
          <form
            onSubmit={(event) => {
              event.preventDefault();
              if (running) update();
              else start();
            }}
          >
            <label className="mb-3 block text-sm">
              <span className="mb-1 block font-medium">{tr("What are you working on?")}</span>
              <input
                autoFocus
                className="v2-input"
                maxLength={2000}
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
              />
            </label>
            <label className="mb-3 block text-sm">
              <span className="mb-1 block font-medium">{tr("Task")}</span>
              <select className="v2-input" value={form.task} onChange={(e) => setForm({ ...form, task: e.target.value })}>
                <option value="">{tr("No task")}</option>
                {tasks.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.title}
                  </option>
                ))}
              </select>
            </label>
            <label className="mb-4 block text-sm">
              <span className="mb-1 block font-medium">{tr("Category")}</span>
              <select className="v2-input" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
                {CATEGORIES.map((c) => (
                  <option key={c.id} value={c.id}>
                    {tr(c.label)}
                  </option>
                ))}
              </select>
            </label>
            <div className="flex gap-2">
              <Button type="submit">{running ? tr("Save") : tr("Start")}</Button>
              {running ? (
                <Button type="button" variant="outline" onClick={stop}>
                  {tr("Stop")}
                </Button>
              ) : null}
              <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
                {tr("Cancel")}
              </Button>
            </div>
          </form>
        </div>
      ) : null}
      {error && !open ? (
        <span role="alert" className="text-xs text-[color:var(--fb-v2-error)]">
          {error}
        </span>
      ) : null}
    </div>
  );
}
