"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { dirFor, useLocale } from "@/i18n";
import { useTr } from "@/i18n/phrases";
import { publicGet } from "@/lib/v2/api";
import "@/styles/v2-tokens.css";

type Portfolio = { name: string; items: { kind: string; title: string; summary: string; organization: string; verify?: string }[] };

/** A person's public portfolio: only the items they chose to make public. */
export default function PortfolioPage() {
  const { slug } = useParams<{ slug: string }>();
  const locale = useLocale();
  const tr = useTr();
  const [page, setPage] = useState<Portfolio | null>(null);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    publicGet<Portfolio>(`/portfolio/${encodeURIComponent(slug)}`)
      .then(setPage)
      .catch(() => setMissing(true));
  }, [slug]);

  return (
    <div className="v2-root min-h-dvh px-4 py-12" dir={dirFor(locale)}>
      <main className="mx-auto max-w-2xl">
        {missing ? (
          <p role="alert">{tr("This portfolio is not public.")}</p>
        ) : !page ? (
          <p role="status">{tr("Loading…")}</p>
        ) : (
          <>
            <h1 className="text-3xl font-semibold tracking-tight">{page.name}</h1>
            <ul className="mt-8 space-y-4">
              {page.items.map((item, i) => (
                <li key={i} className="rounded-xl bg-[color:var(--fb-v2-surface)] p-5">
                  <p className="text-sm text-[color:var(--fb-v2-text-muted)]">{item.organization}</p>
                  <h2 className="text-lg font-semibold">{item.title}</h2>
                  {item.summary ? <p className="mt-1">{item.summary}</p> : null}
                  {item.verify ? (
                    <Link className="mt-2 inline-block text-sm underline" href={item.verify}>
                      {tr("Verify this certificate")}
                    </Link>
                  ) : null}
                </li>
              ))}
            </ul>
          </>
        )}
      </main>
    </div>
  );
}
