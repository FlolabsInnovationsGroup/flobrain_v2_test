import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { writeFile } from "node:fs/promises";
import { test } from "node:test";

import { client } from "../src/api.js";
import { record } from "../src/audio.js";
import { webClientUrl } from "../src/platforms/zoom.js";
import { runSession } from "../src/session.js";

function fakeApi({ leaveAfterInCall = 2, leaveInLobby = false } = {}) {
  const calls = [];
  let inCall = 0;
  return {
    calls,
    status: async (id, status, error = "") => {
      calls.push([status, error]);
      if (status === "in_call") inCall += 1;
      if (status === "waiting_admission" && leaveInLobby && calls.filter((c) => c[0] === "waiting_admission").length > 1) return { leave: true };
      return { leave: inCall > leaveAfterInCall };
    },
    upload: async (id, path) => calls.push(["upload", path.endsWith(".ogg")]),
  };
}

const page = { context: () => ({ close: async () => undefined }) };
const session = { session: "s1", platform: "meet", meeting_url: "https://meet.google.com/abc-defg-hij", bot_name: "FloBrain assistant", announce: "hi", max_minutes: 120 };
const quiet = { log: () => undefined, sleep: async () => undefined };
const writer = (order) => (path) => {
  order?.push("record");
  return { stop: async () => writeFile(path, Buffer.alloc(4096)) };
};

test("joins, announces before recording, records, leaves when told, uploads", async () => {
  const api = fakeApi();
  const order = [];
  const platform = { join: async () => "joined", announce: async () => (order.push("announce"), true), ended: async () => false, participants: async () => 3, leave: async () => order.push("leave") };
  await runSession({ api, session, openPage: async () => page, record: writer(order), platforms: { meet: platform }, ...quiet });
  assert.deepEqual(order, ["announce", "record", "leave"]);
  assert.deepEqual(api.calls.map((c) => c[0]), ["joining", "waiting_admission", "in_call", "in_call", "in_call", "uploading", "upload"]);
});

test("no confirmed announcement means no recording", async () => {
  const api = fakeApi();
  const order = [];
  const platform = { join: async () => "joined", announce: async () => false, ended: async () => false, participants: async () => 3, leave: async () => order.push("leave") };
  await runSession({ api, session, openPage: async () => page, record: writer(order), platforms: { meet: platform }, ...quiet });
  assert.deepEqual(order, ["leave"]);
  assert.deepEqual(api.calls.at(-1), ["failed", "announce_failed"]);
});

test("removed while waiting in the lobby: never records", async () => {
  const api = fakeApi({ leaveInLobby: true });
  const order = [];
  const platform = {
    join: async () => {
      await new Promise((r) => setTimeout(r, 60)); // the heartbeat fires meanwhile
      return "joined";
    },
    announce: async () => true, ended: async () => false, participants: async () => 3, leave: async () => order.push("leave"),
  };
  const result = await runSession({ api, session, openPage: async () => page, record: writer(order), platforms: { meet: platform }, beatMs: 20, ...quiet });
  assert.equal(result.status, "cancelled");
  assert.deepEqual(order, ["leave"]);
  assert.ok(!api.calls.some((c) => c[0] === "upload"));
});

test("not admitted, or alone with nothing recorded: fails without uploading", async () => {
  const api = fakeApi();
  await runSession({ api, session, openPage: async () => page, record: () => ({ stop: async () => undefined }), platforms: { meet: { join: async () => "denied" } }, ...quiet });
  assert.deepEqual(api.calls.at(-1), ["failed", "denied"]);

  const api2 = fakeApi({ leaveAfterInCall: 100 });
  let t = 0;
  const alone = { join: async () => "joined", announce: async () => true, ended: async () => false, participants: async () => 1, leave: async () => true };
  await runSession({ api: api2, session, openPage: async () => page, platforms: { meet: alone }, record: () => ({ stop: async () => undefined }), now: () => (t += 60_000), ...quiet });
  assert.deepEqual(api2.calls.at(-1), ["failed", "no_audio"]);
});

test("the recorder never hangs or crashes", async () => {
  const early = new EventEmitter();
  early.stdin = Object.assign(new EventEmitter(), { write: () => { throw new Error("EPIPE"); } });
  early.stderr = new EventEmitter();
  early.kill = () => undefined;
  const rec = record("/tmp/x.ogg", () => early);
  early.emit("exit", 1); // ffmpeg died before stop()
  assert.equal((await rec.stop()).code, 1);

  const broken = new EventEmitter();
  broken.stdin = new EventEmitter();
  broken.stderr = new EventEmitter();
  broken.kill = () => undefined;
  const rec2 = record("/tmp/y.ogg", () => broken);
  broken.emit("error", new Error("spawn ffmpeg ENOENT")); // no listener would crash the process
  assert.equal((await rec2.stop()).code, -1);
});

test("zoom links become web-client links; the API client sends the worker token", async () => {
  assert.equal(webClientUrl("https://us02web.zoom.us/j/1234567890?pwd=abc"), "https://app.zoom.us/wc/join/1234567890?pwd=abc");
  const seen = [];
  const api = client({ baseUrl: "https://api.test/", token: "fbw_x", fetchImpl: async (url, init) => (seen.push([url, init.headers.Authorization]), { status: 204, ok: true }) });
  assert.equal(await api.claim(), null);
  assert.deepEqual(seen[0], ["https://api.test/api/v2/workers/meeting-bots/claim", "Worker fbw_x"]);
});
