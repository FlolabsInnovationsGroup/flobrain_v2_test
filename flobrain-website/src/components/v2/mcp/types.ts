export type Scope = { key: string; label: string };

export type Overview = {
  endpoint: string;
  resource_metadata: string;
  authorization_server: string;
  scopes: Scope[];
  can_manage: boolean;
  connected_apps: number;
  log_retention_days: number;
};

export type Grant = {
  id: string;
  client: { name: string; client_uri: string; verified: boolean };
  user: { id: string; name: string };
  mine: boolean;
  scopes: Scope[];
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
  revoked_reason: string;
};

export type PolicyTool = { name: string; description: string; read_only: boolean; rule: "allow" | "deny"; usable: boolean };

export type Policy = {
  tool_rules: Record<string, "allow" | "deny">;
  read_only: boolean;
  expires_at: string | null;
  expired: boolean;
  buddy_ids: string[];
  updated_at: string | null;
  tools: PolicyTool[];
};

export type HubServer = {
  id: string;
  name: string;
  host: string;
  demo: boolean;
  allowed: boolean;
  status: "pending" | "connected" | "error";
  tools_approved: boolean;
  policy: Policy;
};

export type HubBuddy = { id: string; name: string; slug: string };

export type CallRow = {
  id: string;
  direction: "inbound" | "outbound";
  client: string;
  server: { id: string; name: string } | null;
  user: { id: string; name: string } | null;
  tool: string;
  ok: boolean;
  error: string;
  duration_ms: number;
  arguments: Record<string, unknown>;
  created_at: string;
};

export type CallLogPage = {
  results: CallRow[];
  total: number;
  errors: number;
  tools: string[];
  clients: string[];
  retention_days: number;
};

export type CallFilters = { direction: "" | "inbound" | "outbound"; ok: "" | "true" | "false"; tool: string; client: string; days: string };

export type ConsentInfo = {
  client: { name: string; client_uri: string; redirect_host: string; verified: boolean; registered_at: string };
  scopes: Scope[];
  resource: string;
  orgs: { id: string; name: string; slug: string; available: boolean }[];
  expires_in: number;
};
