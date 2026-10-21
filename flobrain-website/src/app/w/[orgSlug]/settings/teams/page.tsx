"use client";

import { useState } from "react";

import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { ConfirmButton } from "@/components/v2/shell/ConfirmButton";
import { Button } from "@/components/v2/ui/button";
import { Badge, Field, Notice, PageHeader, Row, Rows, Section } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { has } from "@/lib/v2/access";
import { useAccess } from "@/lib/v2/AccessContext";
import { api, errorText, rowsOf } from "@/lib/v2/api";
import { displayName, type Member } from "@/lib/v2/screens/people";
import { useOrgData } from "@/lib/v2/useOrgData";

type Person = { id: string; username: string };
type Team = { id: string; name: string; description: string; is_active: boolean; member_count: number; leads: Person[]; my_role: string | null };
type TeamMember = { user_id: string; username: string; team_role: "lead" | "member"; weekly_target_hours: string | null; weekly_task_target: number | null; employment_status: string | null };
type Project = {
  id: string;
  name: string;
  description: string;
  status: string;
  lead: string | null;
  lead_user: Person | null;
  teams: { id: string; name: string }[];
  starts_on: string | null;
  due_on: string | null;
  members?: Person[];
  can_edit?: boolean;
  can_manage?: boolean;
};
type Msg = { kind: "ok" | "error"; text: string } | null;

const PROJECT_STATUSES = ["active", "paused", "done", "archived"];

export default function TeamsSettingsPage() {
  const tr = useTr();
  const { orgId, access } = useAccess();
  const teams = useOrgData<Team[]>(orgId, "/teams", { list: true });
  const projects = useOrgData<Project[]>(orgId, "/projects", { list: true });
  const people = useOrgData<{ results: Member[] }>(orgId, "/members?status=active&page_size=100");
  const [openTeam, setOpenTeam] = useState<string | null>(null);
  const [openProject, setOpenProject] = useState<string | null>(null);
  const [message, setMessage] = useState<Msg>(null);
  const canTeams = has(access, "team.manage");
  const canProjects = has(access, "project.manage");
  const everyone = rowsOf<Member>(people.data);
  const isAdmin = access?.org_role === "owner" || access?.org_role === "admin";
  const say = (kind: "ok" | "error", text: string) => setMessage({ kind, text });

  return (
    <div className="max-w-5xl">
      <PageHeader
        title={tr("Teams and projects")}
        intro={
          canTeams
            ? tr("Create teams and projects, choose who leads them and set weekly targets. Every team and project gets its own room.")
            : tr("Edit the teams and projects you lead: details, members and weekly targets.")
        }
      />
      {message ? <Notice kind={message.kind}>{message.text}</Notice> : null}

      <Section title={tr("Teams")}>
        {canTeams && orgId ? (
          <CreateTeam orgId={orgId} people={everyone} onDone={(text) => { say("ok", text); teams.reload(); }} onError={(text) => say("error", text)} />
        ) : null}
        <ScreenBody state={teams.state} error={teams.error} emptyLabel={tr("No teams yet")} onRetry={teams.reload}>
          <Rows>
            {(teams.data ?? []).map((t) => {
              const editable = canTeams || t.my_role === "lead";
              return (
                <Row key={t.id} className="items-start">
                  <div className="min-w-0 flex-1">
                    <p className="font-medium">
                      {t.name} {t.is_active ? null : <Badge>{tr("Archived")}</Badge>}
                    </p>
                    <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
                      {tr("{n} people", { n: t.member_count })}
                      {t.leads.length ? ` · ${tr("Led by {names}", { names: t.leads.map((l) => l.username).join(", ") })}` : ` · ${tr("No lead yet")}`}
                    </p>
                    {openTeam === t.id && orgId ? (
                      <TeamEditor
                        orgId={orgId}
                        team={t}
                        people={everyone}
                        canManage={canTeams}
                        isAdmin={isAdmin}
                        onChange={(text) => {
                          say("ok", text);
                          teams.reload();
                        }}
                        onError={(text) => say("error", text)}
                      />
                    ) : null}
                  </div>
                  {editable ? (
                    <Button variant="outline" onClick={() => setOpenTeam(openTeam === t.id ? null : t.id)}>
                      {openTeam === t.id ? tr("Close") : tr("Edit")}
                    </Button>
                  ) : null}
                </Row>
              );
            })}
          </Rows>
        </ScreenBody>
      </Section>

      <Section title={tr("Projects")}>
        {canProjects && orgId ? (
          <CreateProject
            orgId={orgId}
            people={everyone}
            teams={(teams.data ?? []).filter((t) => t.is_active)}
            onDone={(text) => {
              say("ok", text);
              projects.reload();
            }}
            onError={(text) => say("error", text)}
          />
        ) : null}
        <ScreenBody state={projects.state} error={projects.error} emptyLabel={tr("No projects yet")} onRetry={projects.reload}>
          <Rows>
            {(projects.data ?? []).map((p) => {
              const editable = canProjects || p.lead === access?.user_id;
              return (
                <Row key={p.id} className="items-start">
                  <div className="min-w-0 flex-1">
                    <p className="font-medium">
                      {p.name} <Badge tone={p.status === "active" ? "good" : "neutral"}>{tr(`project|${p.status}`)}</Badge>
                    </p>
                    <p className="text-sm text-[color:var(--fb-v2-text-muted)]">
                      {p.lead_user ? tr("Led by {names}", { names: p.lead_user.username }) : tr("No lead yet")}
                      {p.teams.length ? ` · ${p.teams.map((t) => t.name).join(", ")}` : ""}
                      {p.due_on ? ` · ${tr("Due {date}", { date: p.due_on })}` : ""}
                    </p>
                    {openProject === p.id && orgId ? (
                      <ProjectEditor
                        orgId={orgId}
                        projectId={p.id}
                        people={everyone}
                        teams={(teams.data ?? []).filter((t) => t.is_active)}
                        onChange={(text) => {
                          say("ok", text);
                          projects.reload();
                        }}
                        onError={(text) => say("error", text)}
                      />
                    ) : null}
                  </div>
                  {editable ? (
                    <Button variant="outline" onClick={() => setOpenProject(openProject === p.id ? null : p.id)}>
                      {openProject === p.id ? tr("Close") : tr("Edit")}
                    </Button>
                  ) : null}
                </Row>
              );
            })}
          </Rows>
        </ScreenBody>
      </Section>
    </div>
  );
}

function PersonSelect({ people, value, onChange, label, empty, exclude = [] }: { people: Member[]; value: string; onChange: (v: string) => void; label: string; empty: string; exclude?: string[] }) {
  return (
    <label className="text-sm">
      <span className="sr-only">{label}</span>
      <select className="v2-input" value={value} onChange={(e) => onChange(e.target.value)} aria-label={label}>
        <option value="">{empty}</option>
        {people
          .filter((m) => !exclude.includes(m.id))
          .map((m) => (
            <option key={m.id} value={m.id}>
              {displayName(m)}
            </option>
          ))}
      </select>
    </label>
  );
}

function CreateTeam({ orgId, people, onDone, onError }: { orgId: string; people: Member[]; onDone: (t: string) => void; onError: (t: string) => void }) {
  const tr = useTr();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [lead, setLead] = useState("");
  return (
    <form
      className="mb-4 grid gap-x-4 rounded-xl bg-[color:var(--fb-v2-surface)] p-4 md:grid-cols-3"
      onSubmit={async (e) => {
        e.preventDefault();
        try {
          await api.post(`/orgs/${orgId}/teams`, { name, description, ...(lead ? { lead_id: lead } : {}) });
          onDone(tr("Team {name} created.", { name }));
          setName("");
          setDescription("");
          setLead("");
        } catch (err) {
          onError(errorText(err));
        }
      }}
    >
      <Field label={tr("New team name")}>
        <input className="v2-input" value={name} onChange={(e) => setName(e.target.value)} required maxLength={200} />
      </Field>
      <Field label={tr("Description")}>
        <input className="v2-input" value={description} onChange={(e) => setDescription(e.target.value)} maxLength={2000} />
      </Field>
      <Field label={tr("Lead")}>
        <PersonSelect people={people} value={lead} onChange={setLead} label={tr("Lead")} empty={tr("Choose later")} />
      </Field>
      <div className="md:col-span-3">
        <Button type="submit">{tr("Create team")}</Button>
      </div>
    </form>
  );
}

function TeamEditor({
  orgId,
  team,
  people,
  canManage,
  isAdmin,
  onChange,
  onError,
}: {
  orgId: string;
  team: Team;
  people: Member[];
  canManage: boolean;
  isAdmin: boolean;
  onChange: (t: string) => void;
  onError: (t: string) => void;
}) {
  const tr = useTr();
  const members = useOrgData<TeamMember[]>(orgId, `/teams/${team.id}/members`);
  const [name, setName] = useState(team.name);
  const [description, setDescription] = useState(team.description);
  const [adding, setAdding] = useState("");
  const base = `/orgs/${orgId}/teams/${team.id}`;
  const run = async (fn: () => Promise<unknown>, done: string) => {
    try {
      await fn();
      onChange(done);
      members.reload();
    } catch (err) {
      onError(errorText(err));
    }
  };

  return (
    <div className="mt-3 space-y-4">
      <form
        className="grid gap-x-4 md:grid-cols-2"
        onSubmit={(e) => {
          e.preventDefault();
          void run(() => api.patch(base, { name, description }), tr("Team saved."));
        }}
      >
        <Field label={tr("Name")}>
          <input className="v2-input" value={name} onChange={(e) => setName(e.target.value)} required maxLength={200} />
        </Field>
        <Field label={tr("Description")}>
          <input className="v2-input" value={description} onChange={(e) => setDescription(e.target.value)} maxLength={2000} />
        </Field>
        <div className="flex flex-wrap gap-2 md:col-span-2">
          <Button type="submit">{tr("Save")}</Button>
          {canManage ? (
            team.is_active ? (
              <ConfirmButton
                label={tr("Archive team")}
                variant="danger"
                question={tr("Archive {name}? It disappears from pickers. Its room, tasks and history stay.", { name: team.name })}
                onConfirm={() => run(() => api.patch(base, { is_active: false }), tr("Team archived."))}
              />
            ) : (
              <Button type="button" variant="outline" onClick={() => run(() => api.patch(base, { is_active: true }), tr("Team restored."))}>
                {tr("Restore team")}
              </Button>
            )
          ) : null}
        </div>
      </form>

      <div>
        <h3 className="mb-2 text-sm font-semibold">{tr("Members and weekly targets")}</h3>
        <ScreenBody state={members.state} error={members.error} emptyLabel={tr("Nobody on this team yet")} onRetry={members.reload}>
          <ul className="space-y-2">
            {(members.data ?? []).map((m) => (
              <MemberLine
                key={m.user_id}
                row={m}
                isAdmin={isAdmin}
                onSave={(body, done) => run(() => api.patch(`${base}/members/${m.user_id}`, body), done)}
                onRemove={() => run(() => api.del(`${base}/members/${m.user_id}`), tr("{name} left the team.", { name: m.username }))}
              />
            ))}
          </ul>
        </ScreenBody>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <PersonSelect
            people={people}
            value={adding}
            onChange={setAdding}
            label={tr("Add a person")}
            empty={tr("Add a person")}
            exclude={(members.data ?? []).map((m) => m.user_id)}
          />
          <Button
            variant="outline"
            disabled={!adding}
            onClick={() =>
              run(async () => {
                await api.post(`${base}/members`, { user_id: adding });
                setAdding("");
              }, tr("Added to the team."))
            }
          >
            {tr("Add")}
          </Button>
        </div>
      </div>
    </div>
  );
}

function MemberLine({
  row,
  isAdmin,
  onSave,
  onRemove,
}: {
  row: TeamMember;
  isAdmin: boolean;
  onSave: (body: Record<string, unknown>, done: string) => Promise<void>;
  onRemove: () => Promise<void>;
}) {
  const tr = useTr();
  const [hours, setHours] = useState(row.weekly_target_hours ?? "");
  const [tasks, setTasks] = useState(row.weekly_task_target?.toString() ?? "");
  const canTouch = isAdmin || row.team_role === "member";
  return (
    <li className="flex flex-wrap items-center gap-2 text-sm">
      <span className="min-w-32 flex-1 font-medium">
        {row.username} {row.team_role === "lead" ? <Badge tone="accent">{tr("Lead")}</Badge> : null}
        {row.employment_status && row.employment_status !== "active" ? <Badge>{tr("Inactive")}</Badge> : null}
      </span>
      <label className="flex items-center gap-1">
        <span className="text-[color:var(--fb-v2-text-muted)]">{tr("Hours a week")}</span>
        <input className="v2-input w-20" inputMode="decimal" value={hours} disabled={!canTouch} onChange={(e) => setHours(e.target.value)} />
      </label>
      <label className="flex items-center gap-1">
        <span className="text-[color:var(--fb-v2-text-muted)]">{tr("Tasks a week")}</span>
        <input className="v2-input w-16" inputMode="numeric" value={tasks} disabled={!canTouch} onChange={(e) => setTasks(e.target.value)} />
      </label>
      {canTouch ? (
        <Button
          variant="ghost"
          onClick={() =>
            onSave(
              { weekly_target_hours: hours === "" ? null : hours, weekly_task_target: tasks === "" ? null : Number.isInteger(Number(tasks)) ? Number(tasks) : tasks },
              tr("Targets saved."),
            )
          }
        >
          {tr("Save")}
        </Button>
      ) : null}
      {isAdmin ? (
        <ConfirmButton
          label={row.team_role === "lead" ? tr("Make member") : tr("Make lead")}
          question={
            row.team_role === "lead"
              ? tr("Make {name} a plain member of this team?", { name: row.username })
              : tr("Make {name} a lead of this team? Leads manage its members, tasks and reports.", { name: row.username })
          }
          onConfirm={() => onSave({ team_role: row.team_role === "lead" ? "member" : "lead" }, tr("Role changed."))}
        />
      ) : null}
      {canTouch ? (
        <ConfirmButton
          label={tr("Remove")}
          variant="danger"
          question={tr("Remove {name} from this team? They also leave its room.", { name: row.username })}
          onConfirm={onRemove}
        />
      ) : null}
    </li>
  );
}

function CreateProject({
  orgId,
  people,
  teams,
  onDone,
  onError,
}: {
  orgId: string;
  people: Member[];
  teams: Team[];
  onDone: (t: string) => void;
  onError: (t: string) => void;
}) {
  const tr = useTr();
  const [name, setName] = useState("");
  const [lead, setLead] = useState("");
  const [teamIds, setTeamIds] = useState<string[]>([]);
  const [due, setDue] = useState("");
  return (
    <form
      className="mb-4 grid gap-x-4 rounded-xl bg-[color:var(--fb-v2-surface)] p-4 md:grid-cols-3"
      onSubmit={async (e) => {
        e.preventDefault();
        try {
          await api.post(`/orgs/${orgId}/projects`, { name, team_ids: teamIds, ...(lead ? { lead_id: lead } : {}), ...(due ? { due_on: due } : {}) });
          onDone(tr("Project {name} created.", { name }));
          setName("");
          setLead("");
          setTeamIds([]);
          setDue("");
        } catch (err) {
          onError(errorText(err));
        }
      }}
    >
      <Field label={tr("New project name")}>
        <input className="v2-input" value={name} onChange={(e) => setName(e.target.value)} required maxLength={200} />
      </Field>
      <Field label={tr("Lead")}>
        <PersonSelect people={people} value={lead} onChange={setLead} label={tr("Lead")} empty={tr("Choose later")} />
      </Field>
      <Field label={tr("Due date")}>
        <input className="v2-input" type="date" value={due} onChange={(e) => setDue(e.target.value)} />
      </Field>
      <TeamChecks teams={teams} value={teamIds} onChange={setTeamIds} />
      <div className="md:col-span-3">
        <Button type="submit">{tr("Create project")}</Button>
      </div>
    </form>
  );
}

function TeamChecks({ teams, value, onChange, disabled = false }: { teams: Team[]; value: string[]; onChange: (v: string[]) => void; disabled?: boolean }) {
  const tr = useTr();
  return (
    <fieldset className="mb-4 text-sm md:col-span-3" disabled={disabled}>
      <legend className="mb-1 font-medium">{tr("Teams on this project")}</legend>
      {teams.map((t) => (
        <label key={t.id} className="me-4 inline-flex items-center gap-2">
          <input type="checkbox" checked={value.includes(t.id)} onChange={(e) => onChange(e.target.checked ? [...value, t.id] : value.filter((x) => x !== t.id))} />
          {t.name}
        </label>
      ))}
    </fieldset>
  );
}

function ProjectEditor({
  orgId,
  projectId,
  people,
  teams,
  onChange,
  onError,
}: {
  orgId: string;
  projectId: string;
  people: Member[];
  teams: Team[];
  onChange: (t: string) => void;
  onError: (t: string) => void;
}) {
  const detail = useOrgData<Project>(orgId, `/projects/${projectId}`);
  return (
    <ScreenBody state={detail.state} error={detail.error} onRetry={detail.reload}>
      {detail.data ? (
        <ProjectForm
          key={JSON.stringify(detail.data)}
          orgId={orgId}
          project={detail.data}
          people={people}
          teams={teams}
          onChange={(text) => {
            onChange(text);
            detail.reload();
          }}
          onError={onError}
        />
      ) : null}
    </ScreenBody>
  );
}

function ProjectForm({
  orgId,
  project,
  people,
  teams,
  onChange,
  onError,
}: {
  orgId: string;
  project: Project;
  people: Member[];
  teams: Team[];
  onChange: (t: string) => void;
  onError: (t: string) => void;
}) {
  const tr = useTr();
  const manage = !!project.can_manage;
  const [name, setName] = useState(project.name);
  const [description, setDescription] = useState(project.description);
  const [starts, setStarts] = useState(project.starts_on ?? "");
  const [due, setDue] = useState(project.due_on ?? "");
  const [status, setStatus] = useState(project.status);
  const [lead, setLead] = useState(project.lead ?? "");
  const [teamIds, setTeamIds] = useState(project.teams.map((t) => t.id));
  const [adding, setAdding] = useState("");
  const base = `/orgs/${orgId}/projects/${project.id}`;
  const run = async (fn: () => Promise<unknown>, done: string) => {
    try {
      await fn();
      onChange(done);
    } catch (err) {
      onError(errorText(err));
    }
  };

  return (
    <div className="mt-3 space-y-4">
      <form
        className="grid gap-x-4 md:grid-cols-2"
        onSubmit={(e) => {
          e.preventDefault();
          const body: Record<string, unknown> = { name, description, starts_on: starts || null, due_on: due || null };
          if (manage) Object.assign(body, { lead_id: lead || null, team_ids: teamIds });
          void run(() => api.patch(base, body), tr("Project saved."));
        }}
      >
        <Field label={tr("Name")}>
          <input className="v2-input" value={name} onChange={(e) => setName(e.target.value)} required maxLength={200} />
        </Field>
        <Field label={tr("Description")}>
          <input className="v2-input" value={description} onChange={(e) => setDescription(e.target.value)} maxLength={4000} />
        </Field>
        <Field label={tr("Starts")}>
          <input className="v2-input" type="date" value={starts} onChange={(e) => setStarts(e.target.value)} />
        </Field>
        <Field label={tr("Due date")}>
          <input className="v2-input" type="date" value={due} onChange={(e) => setDue(e.target.value)} />
        </Field>
        {manage ? (
          <>
            <Field label={tr("Lead")}>
              <PersonSelect people={people} value={lead} onChange={setLead} label={tr("Lead")} empty={tr("No lead")} />
            </Field>
            <TeamChecks teams={teams} value={teamIds} onChange={setTeamIds} />
          </>
        ) : null}
        <div className="flex flex-wrap items-end gap-2 md:col-span-2">
          <Button type="submit">{tr("Save")}</Button>
          {manage ? (
            <>
              <label className="text-sm">
                <span className="sr-only">{tr("Status")}</span>
                <select className="v2-input w-36" value={status} onChange={(e) => setStatus(e.target.value)}>
                  {PROJECT_STATUSES.map((s) => (
                    <option key={s} value={s}>
                      {tr(`project|${s}`)}
                    </option>
                  ))}
                </select>
              </label>
              <ConfirmButton
                label={tr("Change status")}
                variant={status === "archived" ? "danger" : "outline"}
                disabled={status === project.status}
                question={
                  status === "archived"
                    ? tr("Archive {name}? It leaves pickers; its room and tasks stay readable.", { name: project.name })
                    : tr("Set {name} to {status}?", { name: project.name, status: tr(`project|${status}`) })
                }
                onConfirm={() => run(() => api.patch(base, { status }), tr("Status changed."))}
              />
            </>
          ) : null}
        </div>
      </form>

      <div>
        <h3 className="mb-2 text-sm font-semibold">{tr("People added directly")}</h3>
        <p className="mb-2 text-sm text-[color:var(--fb-v2-text-muted)]">{tr("Everyone on the project's teams is on it already. Add others here.")}</p>
        {project.members?.length ? (
          <ul className="mb-2 space-y-1 text-sm">
            {project.members.map((m) => (
              <li key={m.id} className="flex items-center gap-2">
                <span className="flex-1">{m.username}</span>
                <ConfirmButton
                  label={tr("Remove")}
                  variant="ghost"
                  question={tr("Remove {name} from this project?", { name: m.username })}
                  onConfirm={() => run(() => api.del(`${base}/members/${m.id}`), tr("Removed from the project."))}
                />
              </li>
            ))}
          </ul>
        ) : null}
        <div className="flex flex-wrap items-center gap-2">
          <PersonSelect
            people={people}
            value={adding}
            onChange={setAdding}
            label={tr("Add a person")}
            empty={tr("Add a person")}
            exclude={(project.members ?? []).map((m) => m.id)}
          />
          <Button variant="outline" disabled={!adding} onClick={() => run(() => api.post(`${base}/members`, { user_id: adding }), tr("Added to the project."))}>
            {tr("Add")}
          </Button>
        </div>
      </div>
    </div>
  );
}
