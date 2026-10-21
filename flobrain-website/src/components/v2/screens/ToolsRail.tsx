"use client";

import { Gauge, Plus } from "lucide-react";
import Link from "next/link";

import { BrandMark } from "@/components/v2/shell/BrandMark";
import { useTr } from "@/i18n/phrases";
import { has } from "@/lib/v2/access";
import { useAccess } from "@/lib/v2/AccessContext";
import { rowsOf } from "@/lib/v2/api";
import type { ToolRow } from "@/lib/v2/screens/tools";
import { useOrgData } from "@/lib/v2/useOrgData";

function initials(name: string): string {
  return (
    name
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((p) => p[0]?.toUpperCase())
      .join("") || "?"
  );
}

/**
 * The far-left icon rail (spec 10.1): your external tools (org defaults and your own) open in a new
 * tab, "Add tool" goes to the tools page, and Mission Control is there for leads and admins.
 * Opening a tool here gives FloBrain AI no access to it (Decision 19).
 */
export function ToolsRail({ orgSlug }: { orgSlug: string }) {
  const tr = useTr();
  const { orgId, access } = useAccess();
  const tools = useOrgData<ToolRow[]>(orgId, "/tools");
  const item =
    "flex h-9 w-9 items-center justify-center rounded-[10px] text-xs font-semibold text-[color:var(--fb-v2-text-faint)] transition-colors hover:bg-[color:var(--fb-v2-raised)] hover:text-[color:var(--fb-v2-text)]";

  return (
    <nav aria-label={tr("Tools")} className="hidden w-14 shrink-0 flex-col items-center gap-2 border-e border-[color:var(--fb-v2-border)] bg-[color:var(--fb-v2-void)] py-3 md:flex">
      <Link href={`/w/${orgSlug}`} className="mb-2 flex h-9 w-9 items-center justify-center" aria-label="FloBrain">
        <BrandMark size={26} />
      </Link>
      {has(access, "mission.view") ? (
        <Link href={`/w/${orgSlug}/mission-control`} className={item} title={tr("Mission Control")} aria-label={tr("Mission Control")}>
          <Gauge size={20} aria-hidden />
        </Link>
      ) : null}
      <ul className="flex flex-col items-center gap-2">
        {rowsOf<ToolRow>(tools.data).map((tool) => (
          <li key={tool.id}>
            <a
              href={tool.url}
              target="_blank"
              rel="noopener noreferrer"
              className={`${item} ring-1 ring-inset ring-[color:var(--fb-v2-border)]`}
              title={tool.name}
              aria-label={tr("Open {tool} in a new tab", { tool: tool.name })}
            >
              {initials(tool.name)}
            </a>
          </li>
        ))}
      </ul>
      <Link href={`/w/${orgSlug}/tools`} className={item} title={tr("Add tool")} aria-label={tr("Add tool")}>
        <Plus size={18} aria-hidden />
      </Link>
    </nav>
  );
}
