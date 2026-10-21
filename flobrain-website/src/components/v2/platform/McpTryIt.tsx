"use client";

import { useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Field, Notice } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { getApiBaseUrl } from "@/lib/axios";

type Tool = { name: string; description: string; annotations?: { readOnlyHint?: boolean } };

/**
 * Calls FloBrain's MCP server (``POST /api/mcp``, ``tools/list``) with a personal access token,
 * exactly as an AI assistant would. The token stays in this page's memory only.
 * Give it ``key={token}`` to start over with a new token.
 */
export function McpTryIt({ initialToken = "" }: { initialToken?: string }) {
  const tr = useTr();
  const [token, setToken] = useState(initialToken);
  const [tools, setTools] = useState<Tool[] | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const endpoint = `${getApiBaseUrl()}/api/mcp`;

  async function run() {
    setBusy(true);
    setError("");
    setTools(null);
    try {
      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token.trim()}` },
        body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list", params: {} }),
      });
      const body = await res.json().catch(() => null);
      if (!res.ok || !body || body.error) {
        const msg = body?.error?.message || body?.details || body?.detail || `HTTP ${res.status}`;
        setError(res.status === 403 && /mcp/.test(String(msg)) ? tr("This token does not have the MCP scope.") : String(msg));
        return;
      }
      setTools(body.result?.tools ?? []);
    } catch {
      setError(tr("The server did not answer. Check that the API is running."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-xl bg-[color:var(--fb-v2-surface)] p-4">
      <p className="mb-3 text-sm text-[color:var(--fb-v2-text-muted)]">
        {tr("Ask FloBrain's MCP server which tools this token can use, the same request an AI assistant sends.")}
      </p>
      <Field label={tr("Token")} hint={tr("Paste a token with the MCP scope. It is not saved.")}>
        <input className="v2-input font-mono" type="password" autoComplete="off" value={token} onChange={(e) => setToken(e.target.value)} />
      </Field>
      <pre className="mb-3 overflow-x-auto rounded-lg bg-[color:var(--fb-v2-page)] p-3 text-xs" dir="ltr">
        {`curl -X POST ${endpoint} \\\n  -H "Authorization: Bearer fbp_…" -H "Content-Type: application/json" \\\n  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'`}
      </pre>
      <Button variant="outline" disabled={!token.trim() || busy} onClick={run}>
        {busy ? tr("Asking…") : tr("List tools")}
      </Button>
      {error ? <Notice kind="error">{error}</Notice> : null}
      {tools ? (
        tools.length ? (
          <ul className="mt-3 space-y-1 text-sm">
            {tools.map((t) => (
              <li key={t.name}>
                <code className="font-medium">{t.name}</code>{" "}
                <span className="text-[color:var(--fb-v2-text-muted)]">
                  {t.description} {t.annotations?.readOnlyHint === false ? tr("(asks you for approval)") : ""}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <Notice>{tr("No tools. Give the token a read scope such as tasks or rooms.")}</Notice>
        )
      ) : null}
    </div>
  );
}
