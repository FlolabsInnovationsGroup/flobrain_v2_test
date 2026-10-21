import { describe, expect, it } from "vitest";

import { connectionTone, conversationTone, embedSnippet, parseOrigins, parseTopics, randomToken, sortInbox, type Conversation } from "./logic";

const conv = (over: Partial<Conversation>): Conversation => ({
  id: "x",
  channel: "website",
  connection: "c",
  customer_name: "A",
  contact: "",
  status: "open",
  mode: "buddy",
  escalation_reason: "",
  assigned_room: null,
  assigned_room_name: "",
  assignee: null,
  demo: false,
  last_message_at: "2026-10-21T10:00:00Z",
  ...over,
});

describe("channels logic", () => {
  it("builds the embed snippet", () => {
    expect(embedSnippet("https://app.flobrain.example/", "abc")).toBe('<script src="https://app.flobrain.example/v2/widget.js" data-site="abc" async></script>');
    expect(embedSnippet("https://a.example", "k", "ar")).toContain('data-lang="ar"');
  });

  it("makes tokens that pass the backend rules", () => {
    const token = randomToken(32);
    expect(token).toMatch(/^[A-Za-z0-9_-]{32}$/);
    expect(randomToken(4, () => new Uint8Array([0, 1, 2, 63]))).toBe("ABC_");
  });

  it("parses origins and topics", () => {
    expect(parseOrigins("https://a.example/, https://b.example\nhttps://a.example")).toEqual(["https://a.example", "https://b.example"]);
    expect(parseTopics("refund\n lawyer, refund ,")).toEqual(["refund", "lawyer"]);
  });

  it("uses amber only for drafts waiting for approval", () => {
    expect(conversationTone({ status: "open", drafts: 1 })).toBe("waiting");
    expect(conversationTone({ status: "waiting_human", drafts: 0 })).not.toBe("waiting");
    expect(connectionTone("error")).toBe("bad");
    expect(connectionTone("active")).toBe("good");
  });

  it("puts drafts and waiting customers first", () => {
    const rows = sortInbox([
      conv({ id: "resolved", status: "resolved", last_message_at: "2026-10-21T12:00:00Z" }),
      conv({ id: "open-new", last_message_at: "2026-10-21T11:00:00Z" }),
      conv({ id: "waiting", status: "waiting_human" }),
      conv({ id: "draft", drafts: 1, last_message_at: "2026-10-20T09:00:00Z" }),
    ]);
    expect(rows.map((r) => r.id)).toEqual(["draft", "waiting", "open-new", "resolved"]);
  });
});
