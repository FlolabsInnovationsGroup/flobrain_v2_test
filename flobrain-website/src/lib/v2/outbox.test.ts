import { beforeEach, describe, expect, it } from "vitest";

import { flush, pending, queue } from "./outbox";

class MemoryStorage {
  data = new Map<string, string>();
  getItem(k: string) {
    return this.data.get(k) ?? null;
  }
  setItem(k: string, v: string) {
    this.data.set(k, v);
  }
  removeItem(k: string) {
    this.data.delete(k);
  }
}

function signInAs(sub: string) {
  const payload = btoa(JSON.stringify({ sub })).replace(/=+$/, "");
  (globalThis as unknown as { window: { localStorage: MemoryStorage } }).window.localStorage.setItem("flobrain_access_token", `h.${payload}.s`);
}

beforeEach(() => {
  (globalThis as unknown as { window: { localStorage: MemoryStorage } }).window = { localStorage: new MemoryStorage() };
  signInAs("u1");
});

describe("outbox", () => {
  it("keeps order and stops at a network failure", async () => {
    queue("o", "r1", "one");
    queue("o", "r1", "two");
    queue("o", "r2", "three");
    expect(pending("r1").map((r) => r.body)).toEqual(["one", "two"]);
    const sent: string[] = [];
    let offline = true;
    const send = async (row: { body: string }) => {
      if (offline && row.body === "two") throw new Error("network");
      sent.push(row.body);
    };
    expect(await flush(send, () => true)).toBe(1);
    expect(pending().map((r) => r.body)).toEqual(["two", "three"]);
    offline = false;
    expect(await flush(send, () => true)).toBe(2);
    expect(sent).toEqual(["one", "two", "three"]);
    expect(pending()).toEqual([]);
  });

  it("drops messages the server refuses", async () => {
    queue("o", "r", "forbidden");
    expect(await flush(async () => Promise.reject(new Error("403")), () => false)).toBe(0);
    expect(pending()).toEqual([]);
  });

  it("never sends another person's queued messages", async () => {
    queue("o", "r1", "from u1");
    signInAs("u2");
    expect(pending()).toEqual([]);
    const sent: string[] = [];
    expect(await flush(async (row) => sent.push(row.body), () => true)).toBe(0);
    signInAs("u1");
    expect(await flush(async (row) => sent.push(row.body), () => true)).toBe(1);
    expect(sent).toEqual(["from u1"]);
  });
});
