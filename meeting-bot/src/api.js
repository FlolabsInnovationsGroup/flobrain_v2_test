// FloBrain worker API for meeting bots. Authorization: Worker <token> (a meeting_bot token).
import { readFile } from "node:fs/promises";
import { basename } from "node:path";

export function client({ baseUrl, token, fetchImpl = fetch }) {
  const root = baseUrl.replace(/\/+$/, "") + "/api/v2/workers/meeting-bots";
  const headers = { Authorization: `Worker ${token}` };

  async function call(path, init = {}) {
    const res = await fetchImpl(root + path, { ...init, headers: { ...headers, ...(init.headers || {}) } });
    if (res.status === 204) return null;
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      const err = new Error(`FloBrain ${res.status}: ${body.error || "error"}`);
      err.status = res.status;
      throw err;
    }
    return body;
  }

  return {
    claim: () => call("/claim", { method: "POST" }),
    status: (session, status, error = "") =>
      call(`/${session}/status`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status, error }) }),
    async upload(session, filePath, contentType = "audio/ogg") {
      const form = new FormData();
      form.append("file", new Blob([await readFile(filePath)], { type: contentType }), basename(filePath));
      return call(`/${session}/audio`, { method: "POST", body: form });
    },
  };
}
