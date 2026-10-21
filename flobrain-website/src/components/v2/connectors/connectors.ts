/** Types and pure helpers for write-back connectors (growth round W4). */

export type ProviderStatus = "not_set_up" | "not_connected" | "connected" | "connected_personal" | "expired" | "error";
export type Risk = "high" | "medium";
export type LogState = "waiting" | "done" | "failed" | "rejected" | "expired";

export type WriteAction = {
  tool: string;
  key: string;
  label: string;
  description: string;
  risk: Risk;
  scopes: string[];
  enabled: boolean;
};

export type WriteConnection = {
  id: string;
  provider: string;
  scope: "org" | "personal";
  account_label: string;
  scopes: string[];
  status: "connected" | "expired" | "error" | "not_set_up";
  last_error: string;
  secret_hint: string;
  expires_at: string | null;
  simulated: boolean;
  site: string;
  connected_at: string;
  last_used_at: string | null;
};

export type WriteProvider = {
  key: string;
  name: string;
  description: string;
  auth: "oauth2" | "api_key";
  per_user: boolean;
  configured: boolean;
  status: ProviderStatus;
  simulated: boolean;
  scopes: string[];
  connection: WriteConnection | null;
  personal: WriteConnection | null;
  actions: WriteAction[];
  env?: string[];
};

export type WriteCatalog = {
  providers: WriteProvider[];
  can_manage: boolean;
  can_act: boolean;
  demo: boolean;
  encryption_configured: boolean;
};

export type LogRow = {
  id: string;
  tool: string;
  provider: string;
  provider_name: string;
  label: string;
  risk: Risk | "";
  summary: string;
  status: string;
  state: LogState | string;
  url: string;
  simulated: boolean;
  error: string;
  by: string;
  created_at: string;
  decided_at: string | null;
};

export type Tone = "neutral" | "waiting" | "good" | "bad" | "accent";

/** Card badge for a provider. Rose only when something is broken; green when it works. */
export function statusBadge(status: ProviderStatus | string): { tone: Tone; label: string } {
  switch (status) {
    case "connected":
      return { tone: "good", label: "Connected" };
    case "connected_personal":
      return { tone: "good", label: "Your account is connected" };
    case "expired":
      return { tone: "bad", label: "Expired" };
    case "error":
      return { tone: "bad", label: "Needs attention" };
    case "not_set_up":
      return { tone: "neutral", label: "Not set up yet" };
    default:
      return { tone: "neutral", label: "Not connected" };
  }
}

/** Log badge: amber waits for approval, green is done, rose failed, the rest is neutral. */
export function logBadge(state: LogState | string): { tone: Tone; label: string } {
  switch (state) {
    case "waiting":
      return { tone: "waiting", label: "Waiting for approval" };
    case "done":
      return { tone: "good", label: "Done" };
    case "failed":
      return { tone: "bad", label: "Failed" };
    case "rejected":
      return { tone: "neutral", label: "Rejected" };
    case "expired":
      return { tone: "neutral", label: "Expired" };
    default:
      return { tone: "neutral", label: state };
  }
}

export function riskLabel(risk: Risk | ""): string {
  return risk === "high" ? "Sends or bills" : "Creates or updates";
}

/** What a person can do with a provider card right now. */
export function cardActions(p: WriteProvider, canManage: boolean, canAct: boolean, demo: boolean) {
  const available = p.configured || demo;
  const org = p.connection;
  return {
    connectOrg: available && canManage && !org,
    reconnectOrg: available && canManage && !!org && org.status !== "connected",
    disconnectOrg: canManage && !!org,
    connectPersonal: available && canAct && p.per_user && !p.personal,
    disconnectPersonal: !!p.personal,
    apiKeyForm: p.auth === "api_key",
  };
}

/** Read the OAuth return (``?write_result=...&write_confirm=...``) from the page URL. */
export function oauthReturn(search: string): { result: string; code: string; provider: string } | null {
  const params = new URLSearchParams(search);
  const result = params.get("write_result");
  if (!result) return null;
  return { result, code: params.get("write_confirm") ?? "", provider: params.get("provider") ?? "" };
}

/** The page URL without the OAuth return parameters, so a reload doesn't confirm twice. */
export function withoutOAuthParams(href: string): string {
  const url = new URL(href);
  for (const key of ["write_result", "write_confirm", "provider"]) url.searchParams.delete(key);
  return url.pathname + (url.search ? url.search : "") + url.hash;
}

export function oauthResultText(result: string): string {
  switch (result) {
    case "invalid_state":
      return "That sign-in link expired or was already used. Start connecting again.";
    case "exchange_failed":
      return "The app did not accept the sign-in. Try again, and allow every permission it asks for.";
    case "not_configured":
      return "This app is not set up on this server yet.";
    default:
      return "Connecting did not finish. Start again.";
  }
}

/** A short, readable scope: the last part of a URL scope. */
export function scopeLabel(scope: string): string {
  const trimmed = scope.replace(/\/+$/, "");
  return trimmed.includes("/") ? trimmed.slice(trimmed.lastIndexOf("/") + 1) : trimmed;
}

/** Odoo form check before sending: https URL, database, login, key of 8+ characters. */
export function odooFormProblem(form: { url: string; database: string; login: string; api_key: string }): string | null {
  if (!/^https:\/\/[^\s/]+\/?$/i.test(form.url.trim())) return "Use the https address of your Odoo, like https://yourcompany.odoo.com";
  if (!/^[A-Za-z0-9_.-]{1,63}$/.test(form.database.trim())) return "Enter the Odoo database name.";
  if (!form.login.trim()) return "Enter the Odoo login.";
  if (!/^[\x21-\x7e]{8,256}$/.test(form.api_key)) return "The API key is at least 8 characters, without spaces.";
  return null;
}

export function countBy(rows: LogRow[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const row of rows) out[row.state] = (out[row.state] ?? 0) + 1;
  return out;
}
