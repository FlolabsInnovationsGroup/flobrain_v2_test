"use client";

import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Badge } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";

import {
  addStep,
  MAX_STEPS,
  moveStep,
  NEEDS_APPROVAL,
  removeStep,
  ROLES,
  ROOM_TRIGGERS,
  STEP_TYPES,
  stepIssues,
  triggerIssues,
  updateStep,
  defaultTrigger,
  type Step,
  type StepType,
  type Trigger,
  type TriggerType,
  type Workflow,
} from "./steps";
import { contextLabel, roleLabel, stepTypeLabel, triggerTypeLabel, weekdayLabel, WEEKDAYS, type RoomOption } from "./types";

const TRIGGER_TYPES: TriggerType[] = ["schedule", "task_blocked", "task_created", "room_message", "meeting_ended", "customer_conversation", "webhook", "manual"];
const CONTEXTS = ["none", "blocked_tasks", "overdue_tasks", "tasks_due_today", "recent_tasks", "trigger"];

const card = "rounded-xl border border-[color:var(--fb-v2-border)] bg-[color:var(--fb-v2-surface)] p-4";
const label = "mb-1 block text-xs font-medium text-[color:var(--fb-v2-text-muted)]";

function str(value: unknown): string {
  return typeof value === "string" ? value : value == null ? "" : String(value);
}

function RoomSelect({ value, rooms, onChange, allowTrigger, id }: { value: string; rooms: RoomOption[]; onChange: (v: string) => void; allowTrigger?: boolean; id: string }) {
  const tr = useTr();
  return (
    <select id={id} className="v2-input w-full" value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">{tr("Pick a room")}</option>
      {allowTrigger ? <option value="trigger">{tr("The room that started it")}</option> : null}
      {rooms.map((room) => (
        <option key={room.id} value={room.id}>
          {room.name}
        </option>
      ))}
    </select>
  );
}

function TriggerCard({ trigger, rooms, onChange, readOnly }: { trigger: Trigger; rooms: RoomOption[]; onChange: (t: Trigger) => void; readOnly?: boolean }) {
  const tr = useTr();
  const issues = triggerIssues(trigger);
  const set = (patch: Partial<Trigger>) => onChange({ ...trigger, ...patch });
  return (
    <fieldset className={card} disabled={readOnly}>
      <legend className="sr-only">{tr("When it runs")}</legend>
      <p className="mb-3 text-sm font-semibold">{tr("When it runs")}</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block text-sm">
          <span className={label}>{tr("Trigger")}</span>
          <select className="v2-input w-full" value={trigger.type} onChange={(e) => onChange(defaultTrigger(e.target.value as TriggerType))}>
            {TRIGGER_TYPES.map((type) => (
              <option key={type} value={type}>
                {triggerTypeLabel(tr, type)}
              </option>
            ))}
          </select>
        </label>
        {trigger.type === "schedule" ? (
          <label className="block text-sm">
            <span className={label}>{tr("How often")}</span>
            <select className="v2-input w-full" value={trigger.every ?? "day"} onChange={(e) => set({ every: e.target.value as Trigger["every"], weekday: e.target.value === "week" ? 0 : undefined, day: e.target.value === "month" ? 1 : undefined, hours: e.target.value === "hours" ? 4 : undefined, at: e.target.value === "hours" ? undefined : trigger.at ?? "09:00" })}>
              <option value="day">{tr("Every day")}</option>
              <option value="week">{tr("Every week")}</option>
              <option value="month">{tr("Every month")}</option>
              <option value="hours">{tr("Every few hours")}</option>
            </select>
          </label>
        ) : null}
        {trigger.type === "schedule" && trigger.every === "week" ? (
          <label className="block text-sm">
            <span className={label}>{tr("Day")}</span>
            <select className="v2-input w-full" value={trigger.weekday ?? 0} onChange={(e) => set({ weekday: Number(e.target.value) })}>
              {WEEKDAYS.map((d) => (
                <option key={d} value={d}>
                  {weekdayLabel(tr, d)}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        {trigger.type === "schedule" && trigger.every === "month" ? (
          <label className="block text-sm">
            <span className={label}>{tr("Day of the month (1 to 28)")}</span>
            <input className="v2-input w-full" type="number" min={1} max={28} value={trigger.day ?? 1} onChange={(e) => set({ day: Math.min(28, Math.max(1, Number(e.target.value) || 1)) })} />
          </label>
        ) : null}
        {trigger.type === "schedule" && trigger.every === "hours" ? (
          <label className="block text-sm">
            <span className={label}>{tr("Every how many hours (1 to 24)")}</span>
            <input className="v2-input w-full" type="number" min={1} max={24} value={trigger.hours ?? 4} onChange={(e) => set({ hours: Math.min(24, Math.max(1, Number(e.target.value) || 1)) })} />
          </label>
        ) : null}
        {trigger.type === "schedule" && trigger.every !== "hours" ? (
          <label className="block text-sm">
            <span className={label}>{tr("Time")}</span>
            <input className="v2-input w-full" type="time" value={trigger.at ?? "09:00"} onChange={(e) => set({ at: e.target.value })} />
          </label>
        ) : null}
        {trigger.type === "room_message" ? (
          <>
            <label className="block text-sm">
              <span className={label}>{tr("Room")}</span>
              <RoomSelect id="trigger-room" value={trigger.room ?? ""} rooms={rooms} onChange={(room) => set({ room })} />
            </label>
            <label className="block text-sm">
              <span className={label}>{tr("Word to listen for")}</span>
              <input className="v2-input w-full" dir="auto" maxLength={60} value={trigger.keyword ?? ""} onChange={(e) => set({ keyword: e.target.value })} />
            </label>
          </>
        ) : null}
        {trigger.type === "meeting_ended" ? (
          <label className="block text-sm">
            <span className={label}>{tr("Only meetings in this room (optional)")}</span>
            <select className="v2-input w-full" value={trigger.room ?? ""} onChange={(e) => set({ room: e.target.value || undefined })}>
              <option value="">{tr("Any room")}</option>
              {rooms.map((room) => (
                <option key={room.id} value={room.id}>
                  {room.name}
                </option>
              ))}
            </select>
          </label>
        ) : null}
      </div>
      {trigger.type === "schedule" ? <p className="mt-2 text-xs text-[color:var(--fb-v2-text-muted)]">{tr("Times use the organization's time zone.")}</p> : null}
      {trigger.type === "webhook" ? <p className="mt-2 text-xs text-[color:var(--fb-v2-text-muted)]">{tr("After saving, get the signing secret from the workflow's details.")}</p> : null}
      {issues.map((issue) => (
        <p key={issue} className="mt-2 text-xs text-[color:var(--fb-v2-error)]">
          {tr(issue)}
        </p>
      ))}
    </fieldset>
  );
}

function StepFields({ step, index, rooms, trigger, onPatch }: { step: Step; index: number; rooms: RoomOption[]; trigger: Trigger; onPatch: (patch: Record<string, unknown>) => void }) {
  const tr = useTr();
  const id = (field: string) => `step-${index}-${field}`;
  const text = (field: string, title: string, opts: { area?: boolean; max?: number } = {}) => (
    <label className="block text-sm" htmlFor={id(field)}>
      <span className={label}>{title}</span>
      {opts.area ? (
        <textarea id={id(field)} className="v2-input min-h-20 w-full" dir="auto" maxLength={opts.max} value={str(step[field])} onChange={(e) => onPatch({ [field]: e.target.value })} />
      ) : (
        <input id={id(field)} className="v2-input w-full" dir="auto" maxLength={opts.max} value={str(step[field])} onChange={(e) => onPatch({ [field]: e.target.value })} />
      )}
    </label>
  );
  const allowTriggerRoom = ROOM_TRIGGERS.includes(trigger.type);
  switch (step.type) {
    case "ai_prompt":
      return (
        <div className="grid gap-3">
          {text("prompt", tr("What should the AI do?"), { area: true, max: 4000 })}
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block text-sm">
              <span className={label}>{tr("Data it can read")}</span>
              <select className="v2-input w-full" value={str(step.context) || "none"} onChange={(e) => onPatch({ context: e.target.value })}>
                {CONTEXTS.map((c) => (
                  <option key={c} value={c}>
                    {contextLabel(tr, c)}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-sm">
              <span className={label}>{tr("Only tasks from this room (optional)")}</span>
              <select className="v2-input w-full" value={str(step.room)} onChange={(e) => onPatch({ room: e.target.value })}>
                <option value="">{tr("All rooms")}</option>
                {rooms.map((room) => (
                  <option key={room.id} value={room.id}>
                    {room.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>
      );
    case "post_to_room":
      return (
        <div className="grid gap-3">
          <label className="block text-sm" htmlFor={id("room")}>
            <span className={label}>{tr("Room")}</span>
            <RoomSelect id={id("room")} value={str(step.room)} rooms={rooms} allowTrigger={allowTriggerRoom} onChange={(room) => onPatch({ room })} />
          </label>
          {text("text", tr("Message"), { area: true, max: 8000 })}
        </div>
      );
    case "create_task":
      return (
        <div className="grid gap-3 sm:grid-cols-2">
          {text("title", tr("Task title"), { max: 200 })}
          <label className="block text-sm" htmlFor={id("room")}>
            <span className={label}>{tr("Room (optional)")}</span>
            <RoomSelect id={id("room")} value={str(step.room)} rooms={rooms} allowTrigger={allowTriggerRoom} onChange={(room) => onPatch({ room })} />
          </label>
          <label className="block text-sm">
            <span className={label}>{tr("Due in days (optional)")}</span>
            <input className="v2-input w-full" type="number" min={0} max={365} value={step.due_in_days === undefined ? "" : str(step.due_in_days)} onChange={(e) => onPatch({ due_in_days: e.target.value === "" ? undefined : Math.min(365, Math.max(0, Number(e.target.value) || 0)) })} />
          </label>
          <div className="sm:col-span-2">{text("description", tr("Description (optional)"), { area: true, max: 4000 })}</div>
        </div>
      );
    case "notify": {
      const roles = Array.isArray(step.roles) ? (step.roles as string[]) : [];
      return (
        <div className="grid gap-3">
          <fieldset>
            <legend className={label}>{tr("Who gets it")}</legend>
            <div className="flex flex-wrap gap-x-4 gap-y-2">
              {ROLES.map((role) => (
                <label key={role} className="inline-flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={roles.includes(role)} onChange={(e) => onPatch({ roles: e.target.checked ? [...roles, role] : roles.filter((r) => r !== role) })} />
                  {roleLabel(tr, role)}
                </label>
              ))}
            </div>
          </fieldset>
          {text("text", tr("Notification"), { area: true, max: 1000 })}
        </div>
      );
    }
    case "send_email":
      return (
        <div className="grid gap-3">
          <label className="block text-sm" htmlFor={id("to")}>
            <span className={label}>{tr("To (separate addresses with commas)")}</span>
            <input
              id={id("to")}
              className="v2-input w-full"
              dir="ltr"
              value={Array.isArray(step.to) ? (step.to as string[]).join(", ") : ""}
              onChange={(e) => onPatch({ to: e.target.value.split(",").map((s) => s.trim()).filter(Boolean).slice(0, 20) })}
            />
          </label>
          {text("subject", tr("Subject"), { max: 200 })}
          {text("body", tr("Email text"), { area: true, max: 20000 })}
        </div>
      );
    case "call_webhook":
      return (
        <div className="grid gap-3">
          <label className="block text-sm" htmlFor={id("url")}>
            <span className={label}>{tr("Address (https, on the allowed list)")}</span>
            <input id={id("url")} className="v2-input w-full" dir="ltr" maxLength={500} value={str(step.url)} onChange={(e) => onPatch({ url: e.target.value })} />
          </label>
          {text("body", tr("Text to send"), { area: true, max: 20000 })}
        </div>
      );
    case "wait_for_approval":
      return text("message", tr("What are you approving?"), { max: 300 });
    case "nudge_overdue":
      return (
        <label className="block text-sm">
          <span className={label}>{tr("Days overdue before a nudge")}</span>
          <input className="v2-input w-32" type="number" min={0} max={30} value={str(step.min_days_overdue ?? 1)} onChange={(e) => onPatch({ min_days_overdue: Math.min(30, Math.max(0, Number(e.target.value) || 0)) })} />
        </label>
      );
    case "check_budget":
      return (
        <label className="block text-sm">
          <span className={label}>{tr("Continue only above this share of the monthly budget (%)")}</span>
          <input className="v2-input w-32" type="number" min={1} max={100} value={str(step.threshold_pct ?? 80)} onChange={(e) => onPatch({ threshold_pct: Math.min(100, Math.max(1, Number(e.target.value) || 1)) })} />
        </label>
      );
    case "daily_brief":
      return <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Each person gets their own tasks due today, meetings and approvals waiting. People can opt out.")}</p>;
  }
}

/** Trigger card plus an ordered, editable list of step cards. Alt+Up and Alt+Down move the focused step. */
export function WorkflowEditor({ value, onChange, rooms, readOnly }: { value: Workflow; onChange: (w: Workflow) => void; rooms: RoomOption[]; readOnly?: boolean }) {
  const tr = useTr();
  const [adding, setAdding] = useState<StepType>("ai_prompt");
  const focusNext = useRef<number | null>(null);
  const [announce, setAnnounce] = useState("");
  const cards = useRef<(HTMLLIElement | null)[]>([]);
  const issues = stepIssues(value.steps, value.trigger);

  // After a move, add or remove, keep keyboard focus on the step that moved.
  useEffect(() => {
    if (focusNext.current !== null) {
      cards.current[focusNext.current]?.focus();
      focusNext.current = null;
    }
  }, [value.steps]);

  const setSteps = (steps: Step[]) => onChange({ ...value, steps });
  const move = (from: number, to: number) => {
    if (to < 0 || to >= value.steps.length) return;
    setSteps(moveStep(value.steps, from, to));
    focusNext.current = to;
    setAnnounce(tr("Moved to step {n}.", { n: to + 1 }));
  };
  const remove = (index: number) => {
    setSteps(removeStep(value.steps, index));
    focusNext.current = Math.max(0, Math.min(index, value.steps.length - 2));
    setAnnounce(tr("Step removed."));
  };

  return (
    <div className="flex flex-col gap-3">
      <TriggerCard trigger={value.trigger} rooms={rooms} readOnly={readOnly} onChange={(trigger) => onChange({ ...value, trigger })} />
      <p className="text-xs text-[color:var(--fb-v2-text-muted)]">
        {tr("Reuse an earlier step's answer with")} <code dir="ltr">{"{{steps.1.output}}"}</code>. {tr("Use the item that started it with")} <code dir="ltr">{"{{trigger.title}}"}</code>.
      </p>
      <ol className="flex flex-col gap-3" aria-label={tr("Steps")}>
        {value.steps.map((step, index) => (
          <li
            key={index}
            ref={(el) => {
              cards.current[index] = el;
            }}
            tabIndex={-1}
            aria-label={tr("Step {n}: {name}", { n: index + 1, name: stepTypeLabel(tr, step.type) })}
            className={`${card} outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--fb-v2-accent)]`}
            onKeyDown={(e) => {
              if (readOnly || !e.altKey) return;
              if (e.key === "ArrowUp") {
                e.preventDefault();
                move(index, index - 1);
              } else if (e.key === "ArrowDown") {
                e.preventDefault();
                move(index, index + 1);
              }
            }}
          >
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="inline-flex size-6 items-center justify-center rounded-full bg-[color:var(--fb-v2-accent-soft)] text-xs font-semibold" aria-hidden>
                  {index + 1}
                </span>
                <span className="text-sm font-semibold">{stepTypeLabel(tr, step.type)}</span>
                {NEEDS_APPROVAL.includes(step.type) ? <Badge>{tr("Asks for approval")}</Badge> : null}
              </div>
              {readOnly ? null : (
                <div className="flex gap-1">
                  <Button type="button" variant="ghost" disabled={index === 0} aria-label={tr("Move step {n} up", { n: index + 1 })} onClick={() => move(index, index - 1)}>
                    ↑
                  </Button>
                  <Button type="button" variant="ghost" disabled={index === value.steps.length - 1} aria-label={tr("Move step {n} down", { n: index + 1 })} onClick={() => move(index, index + 1)}>
                    ↓
                  </Button>
                  <Button type="button" variant="danger" aria-label={tr("Remove step {n}", { n: index + 1 })} onClick={() => remove(index)}>
                    {tr("Remove")}
                  </Button>
                </div>
              )}
            </div>
            <fieldset disabled={readOnly}>
              <StepFields step={step} index={index} rooms={rooms} trigger={value.trigger} onPatch={(patch) => setSteps(updateStep(value.steps, index, patch))} />
            </fieldset>
            {(issues[index] ?? []).map((issue) => (
              <p key={issue} className="mt-2 text-xs text-[color:var(--fb-v2-error)]">
                {tr(issue)}
              </p>
            ))}
          </li>
        ))}
      </ol>
      <p className="sr-only" aria-live="polite">
        {announce}
      </p>
      {readOnly ? null : (
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-sm">
            <span className={label}>{tr("Add a step")}</span>
            <select className="v2-input" value={adding} onChange={(e) => setAdding(e.target.value as StepType)}>
              {STEP_TYPES.map((type) => (
                <option key={type} value={type}>
                  {stepTypeLabel(tr, type)}
                </option>
              ))}
            </select>
          </label>
          <Button
            type="button"
            variant="outline"
            disabled={value.steps.length >= MAX_STEPS}
            onClick={() => {
              setSteps(addStep(value.steps, adding));
              focusNext.current = value.steps.length;
            }}
          >
            {tr("Add step")}
          </Button>
          <span className="text-xs text-[color:var(--fb-v2-text-muted)]">{tr("{n} of {max} steps. Tip: Alt+Up and Alt+Down move the selected step.", { n: value.steps.length, max: MAX_STEPS })}</span>
        </div>
      )}
    </div>
  );
}
