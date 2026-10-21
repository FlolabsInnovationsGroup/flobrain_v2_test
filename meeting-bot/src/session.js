// One meeting from claim to upload. Every step reports to FloBrain, and FloBrain can tell us to leave
// at any point: while waiting in the lobby, before recording, and during the call.
import { mkdtemp, rm, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { meet } from "./platforms/meet.js";
import { teams } from "./platforms/teams.js";
import { zoom } from "./platforms/zoom.js";

export const PLATFORMS = { meet, teams, zoom };
const MINUTE = 60_000;
const BEAT_MS = 15_000;

export async function runSession({ api, session, openPage, record, platforms = PLATFORMS, now = () => Date.now(), sleep, log = console.log, beatMs = BEAT_MS }) {
  const platform = platforms[session.platform];
  const wait = sleep || ((ms) => new Promise((r) => setTimeout(r, ms)));
  if (!platform) return api.status(session.session, "failed", "unknown_platform");
  const dir = await mkdtemp(join(tmpdir(), "fb-bot-"));
  const audioPath = join(dir, "meeting.ogg");
  let page;
  let recorder;
  let toldToLeave = false;
  const report = async (status, error = "") => {
    const reply = await api.status(session.session, status, error);
    if (reply?.leave) toldToLeave = true;
    return reply;
  };
  try {
    await report("joining");
    page = await openPage();
    await report("waiting_admission");
    if (toldToLeave) return { status: "cancelled" };
    // Keep reporting while the host decides, so FloBrain knows we're alive and can call us back.
    const beat = setInterval(() => {
      report("waiting_admission").catch(() => undefined);
    }, beatMs);
    let outcome;
    try {
      outcome = await platform.join(page, session, (session.admission_timeout_minutes || 10) * MINUTE);
    } finally {
      clearInterval(beat);
    }
    if (toldToLeave) {
      await platform.leave(page).catch(() => undefined);
      return { status: "cancelled" };
    }
    if (outcome !== "joined") {
      log(`session ${session.session}: not joined (${outcome})`);
      await report("failed", outcome);
      return { status: "failed" };
    }
    // Say who we are before recording anything (Decision 37). No confirmed announcement, no recording.
    const announced = await platform.announce(page, session.announce).catch(() => false);
    if (!announced) {
      await platform.leave(page).catch(() => undefined);
      await report("failed", "announce_failed");
      return { status: "failed" };
    }
    await report("in_call");
    if (toldToLeave) {
      await platform.leave(page).catch(() => undefined);
      return { status: "cancelled" };
    }
    recorder = record(audioPath);
    const started = now();
    let aloneSince = null;
    for (;;) {
      await wait(beatMs);
      await report("in_call").catch(() => undefined);
      if (toldToLeave) break;
      if (await platform.ended(page)) break;
      if (now() - started > (session.max_minutes || 120) * MINUTE) break;
      const people = await platform.participants(page);
      if (people !== null && people <= 1) {
        aloneSince = aloneSince ?? now();
        if (now() - aloneSince > (session.leave_when_alone_minutes || 2) * MINUTE) break;
      } else {
        aloneSince = null;
      }
    }
    await platform.leave(page).catch(() => undefined);
    await recorder.stop();
    recorder = null;
    await api.status(session.session, "uploading");
    const size = await stat(audioPath).then((s) => s.size).catch(() => 0);
    if (size < 1024) {
      await api.status(session.session, "failed", "no_audio");
      return { status: "failed" };
    }
    await api.upload(session.session, audioPath, "audio/ogg");
    log(`session ${session.session}: uploaded ${size} bytes`);
    return { status: "done" };
  } catch (err) {
    log(`session ${session.session}: ${err?.message || err}`);
    await api.status(session.session, "failed", String(err?.message || "error").slice(0, 100)).catch(() => undefined);
    return { status: "failed" };
  } finally {
    if (recorder) await recorder.stop().catch(() => undefined);
    if (page) await page.context().close().catch(() => undefined);
    await rm(dir, { recursive: true, force: true }).catch(() => undefined);
  }
}
