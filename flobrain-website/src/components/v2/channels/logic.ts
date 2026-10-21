/** Channels and customer inbox: shared types and small pure helpers (tested in logic.test.ts). */

export type ChannelKind = "whatsapp" | "telegram" | "website";
export type ConnectionStatus = "not_set_up" | "active" | "error";

export type Connection = {
  id: string;
  kind: ChannelKind;
  label: string;
  status: ConnectionStatus;
  config: { phone_number_id?: string; waba_id?: string; display_phone?: string; bot_username?: string; allowed_origins?: string[] };
  secret_hints: Record<string, string>;
  site_key: string | null;
  serve_team: boolean;
  serve_customers: boolean;
  team_buddy: string | null;
  demo: boolean;
  last_error: string;
  last_checked_at: string | null;
  webhook_url: string;
  linked_people: number;
  simulated?: boolean;
};

export type MyLink = { id: string; connection: string; kind: ChannelKind; status: "pending" | "active"; contact: string; linked_at: string | null; expires_at: string | null; code?: string };
export type Linkable = { id: string; kind: ChannelKind; label: string; demo: boolean; contact: string };

export type CustomerSettings = {
  auto_reply: boolean;
  escalation_room: string | null;
  blocked_topics: string[];
  buddy_name: string;
  greeting: string;
  knowledge: { id: string; title: string }[];
  hidden_knowledge: number;
  documents: { id: string; title: string; room: string }[];
  rooms: { id: string; name: string }[];
};

export type ConversationStatus = "open" | "waiting_human" | "resolved";
export type Person = { id: string; name: string } | null;
export type Citation = { n: number; document?: string; title: string; excerpt?: string };
export type CustomerMessage = {
  id: string;
  role: "customer" | "buddy" | "staff" | "system";
  text: string;
  status: "sent" | "draft" | "rejected" | "failed";
  citations: Citation[];
  media: { type?: string };
  author: Person;
  approved_by: Person;
  delivery_error: string;
  created_at: string;
};
export type Conversation = {
  id: string;
  channel: ChannelKind;
  connection: string;
  customer_name: string;
  contact: string;
  status: ConversationStatus;
  mode: "buddy" | "human";
  escalation_reason: string;
  assigned_room: string | null;
  assigned_room_name: string;
  assignee: Person;
  demo: boolean;
  last_message_at: string;
  preview?: string;
  drafts?: number;
  messages?: CustomerMessage[];
  delivered?: boolean;
  error?: string;
};

export type Tone = "neutral" | "waiting" | "good" | "bad" | "accent";

/** Amber only for approval-waiting, rose only for errors, green for live. */
export function connectionTone(status: ConnectionStatus): Tone {
  return status === "active" ? "good" : status === "error" ? "bad" : "neutral";
}

export function conversationTone(c: Pick<Conversation, "status" | "drafts">): Tone {
  if (c.drafts && c.drafts > 0) return "waiting";
  if (c.status === "resolved") return "good";
  if (c.status === "waiting_human") return "accent";
  return "neutral";
}

export const KIND_LABEL: Record<ChannelKind, string> = { whatsapp: "WhatsApp", telegram: "Telegram", website: "Website chat" };

export const STATUS_LABEL: Record<ConversationStatus, string> = {
  open: "state|Open",
  waiting_human: "Waiting for a person",
  resolved: "Resolved",
};

export const REASON_LABEL: Record<string, string> = {
  asked_for_human: "The customer asked for a person",
  blocked_topic: "Blocked topic",
  unsure: "The buddy was not sure",
  ai_unavailable: "AI is not available",
  voice_note: "Voice note",
};

export const DELIVERY_LABEL: Record<string, string> = {
  outside_24h_window: "Not sent: WhatsApp allows free replies only within 24 hours of the customer's last message.",
  invalid_credentials: "Not sent: the channel's credentials were refused.",
  not_active: "Not sent: the channel is not active.",
  rate_limited: "Not sent: the provider asked us to slow down.",
};

/** The script tag a site owner pastes before </body>. */
export function embedSnippet(appOrigin: string, siteKey: string, lang = ""): string {
  const origin = appOrigin.replace(/\/+$/, "");
  const langAttr = lang ? ` data-lang="${lang}"` : "";
  return `<script src="${origin}/v2/widget.js" data-site="${siteKey}"${langAttr} async></script>`;
}

/** A random token for the verify / secret token fields (letters, digits, dashes). */
export function randomToken(length = 32, random: (n: number) => Uint8Array = defaultRandom): string {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
  const bytes = random(length);
  let out = "";
  for (let i = 0; i < length; i += 1) out += alphabet[bytes[i] % alphabet.length];
  return out;
}

function defaultRandom(n: number): Uint8Array {
  const bytes = new Uint8Array(n);
  globalThis.crypto.getRandomValues(bytes);
  return bytes;
}

/** Origins from a textarea: one per line or comma separated, trimmed, without duplicates. */
export function parseOrigins(text: string): string[] {
  const seen = new Set<string>();
  for (const part of text.split(/[\s,]+/)) {
    const value = part.trim().replace(/\/+$/, "");
    if (value) seen.add(value);
  }
  return [...seen];
}

/** Topics from a textarea: one per line or comma separated. */
export function parseTopics(text: string): string[] {
  return [...new Set(text.split(/[\n,]+/).map((t) => t.trim()).filter(Boolean))];
}

/** Drafts first (they wait for someone), then people waiting, then the rest by newest message. */
export function sortInbox(rows: Conversation[]): Conversation[] {
  const rank = (c: Conversation) => (c.drafts ? 0 : c.status === "waiting_human" ? 1 : c.status === "open" ? 2 : 3);
  return [...rows].sort((a, b) => rank(a) - rank(b) || b.last_message_at.localeCompare(a.last_message_at));
}
