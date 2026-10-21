import { describe, expect, it } from "vitest";

import { cardView, installReturn, isTenantId, myLinkOn, statusTone, withoutInstallParams, workspaceFor, type BridgeLink, type Card, type Workspace } from "./logic";

const link = (over: Partial<BridgeLink>): BridgeLink => ({
  id: "l",
  workspace: "w1",
  platform: "slack",
  workspace_name: "Acme",
  status: "active",
  account: "",
  email: "",
  found_via: "flobrain",
  mirror: true,
  confirmed_at: null,
  created_at: "2026-10-21T10:00:00Z",
  ...over,
});

describe("bridges logic", () => {
  it("reads and removes the Slack install return", () => {
    expect(installReturn("?bridge_result=confirm&bridge_confirm=abc")).toEqual({ result: "confirm", code: "abc" });
    expect(installReturn("?tab=1")).toBeNull();
    expect(withoutInstallParams("https://app.example.com/w/demo/settings/bridges?bridge_result=confirm&bridge_confirm=abc&tab=1")).toBe("/w/demo/settings/bridges?tab=1");
  });

  it("checks tenant ids", () => {
    expect(isTenantId(" 72f988bf-86f1-41af-91ab-2d7cd011db47 ")).toBe(true);
    expect(isTenantId("contoso.onmicrosoft.com")).toBe(false);
  });

  it("picks the live workspace and my link on it", () => {
    const ws: Workspace[] = [
      { id: "old", platform: "slack", name: "", status: "disconnected", demo: false },
      { id: "w1", platform: "slack", name: "", status: "active", demo: false },
    ];
    expect(workspaceFor(ws, "slack")?.id).toBe("w1");
    expect(workspaceFor(ws, "teams")).toBeUndefined();
    expect(myLinkOn([link({ id: "p", status: "pending" }), link({ id: "a" })], "w1")?.id).toBe("a");
    expect(myLinkOn([link({ id: "p", status: "pending" }), link({ id: "r", status: "revoked" })], "w1")?.id).toBe("p");
    expect(myLinkOn([link({ workspace: "w2" })], "w1")).toBeUndefined();
  });

  it("maps statuses to the signal colours", () => {
    expect(statusTone("active")).toBe("good");
    expect(statusTone("error")).toBe("bad");
    expect(statusTone("pending")).toBe("waiting");
    expect(statusTone("not_set_up")).toBe("neutral");
  });

  it("reads Slack blocks and Teams cards for the preview", () => {
    const slack: Card = {
      id: "c",
      platform: "slack",
      status: "waiting",
      proposal: { id: "p", summary: "x", status: "proposed", tool: "tasks.create" },
      created_at: "",
      message: {
        blocks: [
          { type: "section", text: { type: "mrkdwn", text: "*Waiting for your approval*\nCreate task: Q&amp;A &lt;draft&gt;" } },
          { type: "context", elements: [{ type: "mrkdwn", text: "Proposed by Planner in FloBrain. Only you can decide." }] },
          { type: "actions", elements: [{ type: "button", text: { type: "plain_text", text: "Approve" } }, { type: "button", text: { type: "plain_text", text: "Reject" } }] },
        ],
      },
    };
    expect(cardView(slack)).toEqual({
      title: "Waiting for your approval",
      summary: "Create task: Q&A <draft>",
      note: "Proposed by Planner in FloBrain. Only you can decide.",
      buttons: ["Approve", "Reject"],
    });
    const teams: Card = {
      ...slack,
      platform: "teams",
      message: {
        attachments: [
          {
            contentType: "application/vnd.microsoft.card.adaptive",
            content: { body: [{ type: "TextBlock", text: "Approved and done" }, { type: "TextBlock", text: "Create task: A" }], actions: [] },
          },
        ],
      },
    };
    expect(cardView(teams)).toEqual({ title: "Approved and done", summary: "Create task: A", note: "", buttons: [] });
  });
});
