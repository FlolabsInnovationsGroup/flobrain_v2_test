import { describe, expect, it } from "vitest";

import {
  cardActions,
  countBy,
  logBadge,
  oauthResultText,
  oauthReturn,
  odooFormProblem,
  scopeLabel,
  statusBadge,
  withoutOAuthParams,
  type LogRow,
  type WriteProvider,
} from "./connectors";

function provider(over: Partial<WriteProvider> = {}): WriteProvider {
  return {
    key: "jira", name: "Jira", description: "", auth: "oauth2", per_user: false, configured: true, status: "not_connected",
    simulated: false, scopes: [], connection: null, personal: null, actions: [], ...over,
  };
}

const conn = (status: "connected" | "expired") => ({
  id: "c1", provider: "jira", scope: "org" as const, account_label: "nile", scopes: [], status, last_error: "", secret_hint: "",
  expires_at: null, simulated: false, site: "", connected_at: "2026-10-01T00:00:00Z", last_used_at: null,
});

describe("write-back badges", () => {
  it("uses amber only for waiting, rose only for failures", () => {
    expect(logBadge("waiting").tone).toBe("waiting");
    expect(logBadge("done").tone).toBe("good");
    expect(logBadge("failed").tone).toBe("bad");
    expect(logBadge("rejected").tone).toBe("neutral");
    expect(statusBadge("connected").tone).toBe("good");
    expect(statusBadge("expired").tone).toBe("bad");
    expect(statusBadge("not_set_up").tone).toBe("neutral");
    expect(statusBadge("not_set_up").label).toBe("Not set up yet");
  });
});

describe("card actions", () => {
  it("lets admins connect the org account once it is set up", () => {
    expect(cardActions(provider(), true, true, false).connectOrg).toBe(true);
    expect(cardActions(provider({ configured: false }), true, true, false).connectOrg).toBe(false);
    expect(cardActions(provider({ configured: false }), true, true, true).connectOrg).toBe(true);
    expect(cardActions(provider(), false, true, false).connectOrg).toBe(false);
  });

  it("offers reconnect for an expired connection and personal accounts only where allowed", () => {
    const expired = cardActions(provider({ connection: conn("expired") }), true, true, false);
    expect(expired.reconnectOrg).toBe(true);
    expect(expired.disconnectOrg).toBe(true);
    expect(cardActions(provider({ connection: conn("connected") }), true, true, false).reconnectOrg).toBe(false);
    expect(cardActions(provider({ per_user: true }), false, true, false).connectPersonal).toBe(true);
    expect(cardActions(provider({ per_user: false }), false, true, false).connectPersonal).toBe(false);
  });
});

describe("OAuth return", () => {
  it("reads and strips the return parameters", () => {
    expect(oauthReturn("?write_result=confirm&write_confirm=abc&provider=jira")).toEqual({ result: "confirm", code: "abc", provider: "jira" });
    expect(oauthReturn("?tab=x")).toBeNull();
    expect(withoutOAuthParams("https://app.example.com/w/demo/integrations?write_result=confirm&write_confirm=abc&provider=jira&tab=1")).toBe(
      "/w/demo/integrations?tab=1",
    );
    expect(oauthResultText("invalid_state")).toContain("expired");
  });
});

describe("helpers", () => {
  it("shortens scopes", () => {
    expect(scopeLabel("https://www.googleapis.com/auth/gmail.send")).toBe("gmail.send");
    expect(scopeLabel("write:jira-work")).toBe("write:jira-work");
  });

  it("checks the Odoo form", () => {
    const ok = { url: "https://nile.odoo.com", database: "nile", login: "ops@example.com", api_key: "abcdefgh12" };
    expect(odooFormProblem(ok)).toBeNull();
    expect(odooFormProblem({ ...ok, url: "http://nile.odoo.com" })).toContain("https");
    expect(odooFormProblem({ ...ok, api_key: "short" })).toContain("8");
    expect(odooFormProblem({ ...ok, database: "" })).toContain("database");
  });

  it("counts log rows by state", () => {
    const rows = [{ state: "done" }, { state: "done" }, { state: "waiting" }] as LogRow[];
    expect(countBy(rows)).toEqual({ done: 2, waiting: 1 });
  });
});
