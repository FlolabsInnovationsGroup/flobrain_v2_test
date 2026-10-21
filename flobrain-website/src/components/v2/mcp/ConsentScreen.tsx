"use client";

import { ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";

import { BrandMark } from "@/components/v2/shell/BrandMark";
import { Loading } from "@/components/v2/states";
import { Button } from "@/components/v2/ui/button";
import { Badge, Notice } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, apiError } from "@/lib/v2/api";

import type { ConsentInfo } from "./types";

type Tr = ReturnType<typeof useTr>;

/** A failed step as one plain sentence. ``details`` is the server's own sentence, when it gave one. */
function problem(tr: Tr, code: string, details = ""): string {
  if (code === "invalid_client") return tr("This app is not registered with FloBrain. Go back to the app and try connecting again.");
  if (code === "invalid_redirect_uri") return tr("This app asked to return to an address it did not register. For your safety, FloBrain stopped here.");
  if (code === "expired") return tr("This request expired. Go back to the app and try connecting again.");
  if (code === "not_implemented") return tr("Connecting apps is not enabled in this organization.");
  if (code === "not_found") return tr("You are not a member of that organization.");
  return details || tr("This request is not valid. Go back to the app and try connecting again.");
}

/** The OAuth consent screen: which app, what it may do, in which organization. Allow or Deny. */
export function ConsentScreen({ request, error: startError }: { request: string; error: string }) {
  const tr = useTr();
  const [info, setInfo] = useState<ConsentInfo | null>(null);
  const [error, setError] = useState(startError ? problem(tr, startError) : "");
  const [org, setOrg] = useState("");
  const [scopes, setScopes] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!request) return;
    api
      .get<ConsentInfo>("/mcp/consent", { request })
      .then((value) => {
        setInfo(value);
        setScopes(value.scopes.map((s) => s.key));
        setOrg(value.orgs.find((o) => o.available)?.id ?? "");
      })
      .catch((err) => setError(problem(tr, apiError(err).code)));
  }, [request, tr]);

  async function answer(decision: "approve" | "deny") {
    setBusy(true);
    setError("");
    try {
      const res = await api.post<{ redirect: string }>("/mcp/consent", { request, decision, org, scopes });
      window.location.assign(res.redirect);
    } catch (err) {
      const e = apiError(err);
      setError(problem(tr, e.code, e.details));
      setBusy(false);
    }
  }

  if (error && !info) {
    return (
      <Card>
        <Notice kind="error">{error}</Notice>
      </Card>
    );
  }
  if (!info) return <Loading />;
  const available = info.orgs.filter((o) => o.available);
  const optional = info.scopes.filter((s) => s.key !== "mcp");

  return (
    <Card>
      <form
        className="flex flex-col gap-5"
        onSubmit={(e) => {
          e.preventDefault();
          void answer("approve");
        }}
      >
        <div>
          <h1 className="text-xl font-semibold">{tr("{app} wants to connect to FloBrain", { app: info.client.name })}</h1>
          <p className="mt-1 flex flex-wrap items-center gap-2 text-sm text-[color:var(--fb-v2-text-muted)]">
            <span>
              {tr("After you allow it, you return to")}{" "}
              <bdi dir="ltr" className="font-mono">
                {info.client.redirect_host}
              </bdi>
            </span>
            {info.client.verified ? <Badge>{tr("Demo")}</Badge> : <Badge>{tr("Not reviewed by FloBrain")}</Badge>}
          </p>
        </div>

        {available.length === 0 ? (
          <Notice kind="error">{tr("None of your organizations allow connecting apps yet. Ask an admin to turn on the MCP hub.")}</Notice>
        ) : (
          <label className="text-sm">
            <span className="mb-1 block font-medium">{tr("Organization")}</span>
            <select className="v2-input" value={org} onChange={(e) => setOrg(e.target.value)} required>
              {info.orgs.map((o) => (
                <option key={o.id} value={o.id} disabled={!o.available}>
                  {o.available ? o.name : tr("{name} (connecting apps is off)", { name: o.name })}
                </option>
              ))}
            </select>
          </label>
        )}

        <fieldset className="text-sm">
          <legend className="mb-2 font-medium">{tr("{app} will be able to", { app: info.client.name })}</legend>
          <ul className="flex flex-col gap-2">
            {optional.map((s) => (
              <li key={s.key}>
                <label className="flex cursor-pointer items-start gap-3 rounded-lg bg-[color:var(--fb-v2-page)] p-3">
                  <input
                    type="checkbox"
                    className="mt-0.5 size-4 accent-[color:var(--fb-v2-accent)]"
                    checked={scopes.includes(s.key)}
                    onChange={() => setScopes((list) => (list.includes(s.key) ? list.filter((x) => x !== s.key) : [...list, s.key]))}
                  />
                  <span>{tr(s.label)}</span>
                </label>
              </li>
            ))}
          </ul>
          <p className="mt-3 flex items-start gap-2 text-[color:var(--fb-v2-text-muted)]">
            <ShieldCheck aria-hidden className="mt-0.5 size-4 shrink-0" />
            {tr("It sees only what you can see. Anything it wants to change waits for your approval in FloBrain. You can disconnect it any time in Settings, MCP and tools.")}
          </p>
        </fieldset>

        {error ? <Notice kind="error">{error}</Notice> : null}
        <div className="flex flex-wrap gap-3">
          <Button type="submit" disabled={busy || !org}>
            {tr("Allow")}
          </Button>
          <Button type="button" variant="outline" disabled={busy} onClick={() => void answer("deny")}>
            {tr("Deny")}
          </Button>
        </div>
      </form>
    </Card>
  );
}

function Card({ children }: { children: React.ReactNode }) {
  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-lg flex-col justify-center gap-6 p-4">
      <BrandMark />
      <div className="rounded-2xl bg-[color:var(--fb-v2-surface)] p-5 ring-1 ring-inset ring-[color:var(--fb-v2-border)] sm:p-6">{children}</div>
    </main>
  );
}
