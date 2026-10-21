/** Slack and Microsoft Teams bridges: types and pure helpers (tested in logic.test.ts). */

export type Platform = "slack" | "teams";
export type WorkspaceStatus = "not_set_up" | "active" | "error" | "disconnected";
export type LinkStatus = "pending" | "active" | "revoked";
export type MirrorKey = "approvals" | "automations" | "escalations";

export type Workspace = {
  id: string;
  platform: Platform;
  name: string;
  status: WorkspaceStatus;
  demo: boolean;
  external_id?: string;
  default_buddy?: string | null;
  mirror?: Record<MirrorKey, boolean>;
  secret_hints?: Record<string, string>;
  bot_user?: string;
  last_error?: string;
  last_checked_at?: string | null;
  linked_people?: number;
  pending_people?: number;
};

export type BridgeLink = {
  id: string;
  workspace: string;
  platform: Platform;
  workspace_name: string;
  status: LinkStatus;
  account: string;
  email: string;
  found_via: "platform" | "flobrain";
  mirror: boolean;
  confirmed_at: string | null;
  created_at: string;
  person?: { id: string; name: string; email: string };
};

export type SetupStatus = {
  slack: { ready: boolean; missing: string[] };
  teams: { ready: boolean; missing: string[]; bot_id: string; jwt_library?: boolean };
  endpoints: Record<string, string>;
  encryption?: boolean;
};

export type Overview = {
  demo: boolean;
  can_manage: boolean;
  ready: Record<Platform, boolean>;
  workspaces: Workspace[];
  my_links: BridgeLink[];
  setup?: SetupStatus;
  buddies?: { id: string; name: string; slug: string }[];
};

export type Card = {
  id: string;
  platform: Platform;
  status: "waiting" | "decided";
  proposal: { id: string; summary: string; status: string; tool: string };
  message: { blocks?: SlackBlock[]; attachments?: TeamsAttachment[] };
  created_at: string;
};

export type SimulateResult = {
  simulated: boolean;
  outcome: string;
  reply: string;
  posts: { call: string; text: string; thread: boolean }[];
  cards: Card[];
};

type SlackText = { type: string; text: string };
export type SlackBlock = {
  type: string;
  text?: SlackText;
  elements?: { type: string; text?: SlackText | string; action_id?: string; value?: string }[];
};
type TeamsAttachment = {
  contentType: string;
  content: { body?: { type: string; text?: string; weight?: string }[]; actions?: { type: string; title: string }[] };
};

export const PLATFORMS: Platform[] = ["slack", "teams"];
export const MIRROR_KEYS: MirrorKey[] = ["approvals", "automations", "escalations"];

export function platformName(p: Platform): string {
  return p === "slack" ? "Slack" : "Microsoft Teams";
}

export function statusTone(status: WorkspaceStatus | LinkStatus): "good" | "bad" | "waiting" | "neutral" {
  if (status === "active") return "good";
  if (status === "error") return "bad";
  if (status === "pending") return "waiting";
  return "neutral";
}

const GUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isTenantId(value: string): boolean {
  return GUID.test(value.trim());
}

/** The workspace for a platform that is still connected (the newest first). */
export function workspaceFor(list: Workspace[], platform: Platform): Workspace | undefined {
  return list.find((w) => w.platform === platform && w.status !== "disconnected");
}

/** My link (active first, then pending) on one workspace. */
export function myLinkOn(links: BridgeLink[], workspaceId: string): BridgeLink | undefined {
  const mine = links.filter((l) => l.workspace === workspaceId && l.status !== "revoked");
  return mine.find((l) => l.status === "active") ?? mine.find((l) => l.status === "pending");
}

/** Read the Slack install return (``?bridge_result=...&bridge_confirm=...``) from the page URL. */
export function installReturn(search: string): { result: string; code: string } | null {
  const params = new URLSearchParams(search);
  const result = params.get("bridge_result");
  if (!result) return null;
  return { result, code: params.get("bridge_confirm") ?? "" };
}

/** The page URL without the install return parameters, so a reload doesn't confirm twice. */
export function withoutInstallParams(href: string): string {
  const url = new URL(href);
  for (const key of ["bridge_result", "bridge_confirm"]) url.searchParams.delete(key);
  return url.pathname + (url.search ? url.search : "") + url.hash;
}

/** What a Slack Block Kit or Teams Adaptive Card approval message says, for the preview. */
export function cardView(card: Card): { title: string; summary: string; note: string; buttons: string[] } {
  const unescape = (s: string) => s.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
  if (card.platform === "slack") {
    const blocks = card.message.blocks ?? [];
    const section = blocks.find((b) => b.type === "section")?.text?.text ?? "";
    const [first, ...rest] = section.split("\n");
    const note = blocks.find((b) => b.type === "context")?.elements?.map((e) => (typeof e.text === "string" ? e.text : (e.text?.text ?? ""))).join(" ") ?? "";
    const buttons = blocks.find((b) => b.type === "actions")?.elements?.map((e) => (typeof e.text === "string" ? e.text : (e.text?.text ?? ""))) ?? [];
    return { title: unescape(first.replace(/^\*|\*$/g, "")), summary: unescape(rest.join("\n")), note: unescape(note), buttons };
  }
  const content = card.message.attachments?.[0]?.content ?? {};
  const texts = (content.body ?? []).map((b) => b.text ?? "");
  return { title: texts[0] ?? "", summary: texts[1] ?? "", note: texts[2] ?? "", buttons: (content.actions ?? []).map((a) => a.title) };
}

/** Save JSON as a file (the Teams app manifest). */
export function jsonBlob(data: unknown): Blob {
  return new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
}

export const DEMO_MENTION = "Project Management Buddy: create a task to send the launch checklist to Delta Clinics";
