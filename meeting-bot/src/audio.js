// Records what the browser plays. Chromium outputs to a PulseAudio null sink; ffmpeg records its monitor.
import { execFile, spawn } from "node:child_process";
import { promisify } from "node:util";

const run = promisify(execFile);
export const SINK = process.env.PULSE_SINK || "flobrain";

export async function ensureSink() {
  const { stdout } = await run("pactl", ["list", "short", "sinks"]).catch(() => ({ stdout: "" }));
  if (!stdout.includes(SINK)) {
    await run("pactl", ["load-module", "module-null-sink", `sink_name=${SINK}`, `sink_properties=device.description=${SINK}`]);
  }
  await run("pactl", ["set-default-sink", SINK]).catch(() => undefined);
}

/** Start recording to an Ogg/Opus file (mono, 16 kHz: what Whisper wants). Returns { stop() }, which always resolves. */
export function record(outPath, spawnImpl = spawn) {
  let exited = null;
  let errors = "";
  const done = [];
  let ff;
  try {
    ff = spawnImpl(
      "ffmpeg",
      ["-hide_banner", "-loglevel", "error", "-y", "-f", "pulse", "-i", `${SINK}.monitor`, "-ac", "1", "-ar", "16000", "-c:a", "libopus", "-b:a", "32k", outPath],
      { stdio: ["pipe", "ignore", "pipe"] },
    );
  } catch (err) {
    exited = { code: -1, errors: String(err?.message || err) };
  }
  const finish = (code) => {
    if (exited) return;
    exited = { code, errors };
    done.splice(0).forEach((resolve) => resolve(exited));
  };
  if (ff) {
    ff.on("error", (err) => {
      errors = (errors + String(err?.message || err)).slice(-2000);
      finish(-1);
    });
    ff.on("exit", (code) => finish(code));
    ff.stdin?.on("error", () => undefined); // EPIPE when ffmpeg already stopped
    ff.stderr?.on("data", (chunk) => {
      errors = (errors + chunk.toString()).slice(-2000);
    });
  }
  return {
    stop: () =>
      new Promise((resolve) => {
        if (exited) return resolve(exited);
        done.push(resolve);
        try {
          ff.stdin?.write("q"); // ffmpeg finishes the file cleanly on "q"
        } catch {
          /* already closed */
        }
        setTimeout(() => {
          if (!exited) ff.kill("SIGINT");
        }, 5000).unref?.();
        setTimeout(() => finish(-2), 15000).unref?.();
      }),
  };
}
