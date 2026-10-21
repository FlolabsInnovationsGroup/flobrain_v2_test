"use client";

import { useState } from "react";

import { Button } from "@/components/v2/ui/button";
import { Notice, when } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { api, errorText } from "@/lib/v2/api";

import { ResultChart } from "./ResultChart";
import { SqlBlock } from "./ResultView";
import type { Card } from "./types";

export function CardTile({ orgId, card, canDelete, onChange }: { orgId: string; card: Card; canDelete: boolean; onChange: () => void }) {
  const tr = useTr();
  const [current, setCurrent] = useState(card);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function refresh() {
    setBusy(true);
    setError("");
    try {
      setCurrent(await api.post<Card>(`/orgs/${orgId}/data/cards/${card.id}/run`));
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="flex min-w-0 flex-col gap-3 rounded-xl border border-[color:var(--fb-v2-border)] p-4">
      <div>
        <h3 className="font-semibold">{current.title}</h3>
        <p className="text-xs text-[color:var(--fb-v2-text-muted)]">
          {current.dataset_name}
          {current.last_run_at ? ` · ${tr("Updated {when}", { when: when(current.last_run_at) })}` : ""}
        </p>
      </div>
      <ResultChart spec={current.chart} result={current.result} title={current.title} />
      <SqlBlock sql={current.sql} />
      {error ? <Notice kind="error">{error}</Notice> : null}
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" onClick={refresh} disabled={busy}>
          {busy ? tr("Refreshing…") : tr("Refresh numbers")}
        </Button>
        {canDelete ? (
          <Button
            variant="danger"
            onClick={async () => {
              try {
                await api.del(`/orgs/${orgId}/data/cards/${card.id}`);
                onChange();
              } catch (err) {
                setError(errorText(err));
              }
            }}
          >
            {tr("Delete")}
          </Button>
        ) : null}
      </div>
    </li>
  );
}
