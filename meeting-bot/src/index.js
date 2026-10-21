// FloBrain meeting assistant. Polls FloBrain for meetings to join, one at a time per process.
//   FLOBRAIN_API_URL=https://api.example.com FLOBRAIN_WORKER_TOKEN=fbw_... node src/index.js
// Run several containers for several meetings at once.
import { chromium } from "playwright-core";

import { client } from "./api.js";
import { ensureSink, record } from "./audio.js";
import { runSession } from "./session.js";

const baseUrl = process.env.FLOBRAIN_API_URL;
const token = process.env.FLOBRAIN_WORKER_TOKEN;
if (!baseUrl || !token) {
  console.error("Set FLOBRAIN_API_URL and FLOBRAIN_WORKER_TOKEN (a meeting_bot worker token).");
  process.exit(2);
}
const api = client({ baseUrl, token });
const POLL_MS = Number(process.env.POLL_SECONDS || 10) * 1000;

async function openPage() {
  const browser = await chromium.launch({
    executablePath: process.env.CHROMIUM_PATH || undefined,
    headless: false, // Meet and Teams refuse headless browsers; the container runs Xvfb
    args: [
      "--use-fake-ui-for-media-stream", // allow mic/camera prompts without a person
      "--use-fake-device-for-media-stream",
      // The fake devices play these files, not Chromium's beep and test pattern: silence and black.
      `--use-file-for-fake-audio-capture=${process.env.SILENT_AUDIO || "/app/media/silence.wav"}`,
      `--use-file-for-fake-video-capture=${process.env.BLACK_VIDEO || "/app/media/black.y4m"}`,
      "--autoplay-policy=no-user-gesture-required",
      "--disable-features=WebRtcHideLocalIpsWithMdns",
      "--no-first-run",
      "--lang=en-US",
    ],
  });
  const context = await browser.newContext({ locale: "en-US", viewport: { width: 1280, height: 720 }, permissions: ["microphone", "camera"] });
  context.on("close", () => browser.close().catch(() => undefined));
  return context.newPage();
}

let stopping = false;
process.on("SIGTERM", () => (stopping = true));
process.on("SIGINT", () => (stopping = true));

await ensureSink();
console.log("meeting bot ready");
while (!stopping) {
  try {
    const session = await api.claim();
    if (session) {
      console.log(`joining ${session.platform} meeting “${session.title}”`);
      await runSession({ api, session, openPage, record });
      continue;
    }
  } catch (err) {
    console.error(`claim failed: ${err.message}`);
  }
  await new Promise((r) => setTimeout(r, POLL_MS));
}
