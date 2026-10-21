"use client";

import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { Tabs } from "@/components/v2/compliance/bits";
import { ControlsPanel } from "@/components/v2/compliance/ControlsPanel";
import { EvidencePanel } from "@/components/v2/compliance/EvidencePanel";
import { ForYouPanel } from "@/components/v2/compliance/ForYouPanel";
import { OverviewPanel } from "@/components/v2/compliance/OverviewPanel";
import { PoliciesPanel } from "@/components/v2/compliance/PoliciesPanel";
import { ReviewsPanel } from "@/components/v2/compliance/ReviewsPanel";
import { TrustEditor } from "@/components/v2/compliance/TrustEditor";
import type { Me, Overview } from "@/components/v2/compliance/types";
import { ScreenBody } from "@/components/v2/screens/ScreenBody";
import { PageHeader } from "@/components/v2/ui/kit";
import { useTr } from "@/i18n/phrases";
import { flag, has } from "@/lib/v2/access";
import { useAccess } from "@/lib/v2/AccessContext";
import { useOrgData } from "@/lib/v2/useOrgData";

type Tab = "overview" | "controls" | "reviews" | "evidence" | "policies" | "trust" | "mine";
const ADMIN_TABS: Tab[] = ["overview", "controls", "reviews", "evidence", "policies", "trust", "mine"];

export default function CompliancePage() {
  return (
    <Suspense>
      <ComplianceScreen />
    </Suspense>
  );
}

function ComplianceScreen() {
  const tr = useTr();
  const { orgSlug } = useParams<{ orgSlug: string }>();
  const params = useSearchParams();
  const router = useRouter();
  const { orgId, access } = useAccess();
  const on = flag(access, "compliance");
  const canView = has(access, "compliance.view");
  const canManage = has(access, "compliance.manage");
  const allowed: Tab[] = canView ? ADMIN_TABS : ["mine"];
  const asked = params.get("tab") as Tab | null;
  const tab: Tab = asked && allowed.includes(asked) ? asked : allowed[0];
  const reviewId = params.get("review");
  const { data: me } = useOrgData<Me>(orgId, on ? "/compliance/me" : null);
  const overview = useOrgData<Overview>(orgId, on && canView && tab === "overview" ? "/compliance/overview" : null);

  function go(next: Tab, extra = "") {
    const q = next === allowed[0] && !extra ? "" : `?tab=${next}${extra}`;
    router.replace(`/w/${orgSlug}/settings/compliance${q}`);
  }

  const forYou = (me?.review_items ?? 0) + (me?.policies_to_read ?? 0);
  const labels: Record<Tab, string> = {
    overview: tr("Overview"),
    controls: tr("Controls"),
    reviews: tr("Access reviews"),
    evidence: tr("Evidence"),
    policies: tr("Policies"),
    trust: tr("Trust center"),
    mine: tr("For you"),
  };

  return (
    <div className="max-w-6xl">
      <PageHeader
        title={tr("Compliance")}
        intro={tr("Get ready for SOC 2 and ISO 27001: see which controls FloBrain can prove for you, review who has access, collect evidence for your auditor and publish a trust page.")}
      />
      <ScreenBody state={!access ? "loading" : on ? "ready" : "off"}>
        {orgId ? (
          <>
            <Tabs
              label={tr("Compliance sections")}
              tabs={allowed.map((t) => ({ key: t, label: labels[t], count: t === "mine" ? forYou : undefined }))}
              current={tab}
              onChange={(t) => go(t)}
            />
            <div role="tabpanel" aria-label={labels[tab]}>
              {tab === "overview" ? (
                <ScreenBody state={overview.state} error={overview.error} onRetry={overview.reload}>
                  {overview.data ? <OverviewPanel data={overview.data} orgSlug={orgSlug} onTab={(t) => go(t)} /> : null}
                </ScreenBody>
              ) : null}
              {tab === "controls" ? <ControlsPanel orgId={orgId} canManage={canManage} /> : null}
              {tab === "reviews" ? <ReviewsPanel orgId={orgId} canManage={canManage} selected={reviewId} onSelect={(id) => go("reviews", id ? `&review=${id}` : "")} /> : null}
              {tab === "evidence" ? <EvidencePanel orgId={orgId} canManage={canManage} /> : null}
              {tab === "policies" ? <PoliciesPanel orgId={orgId} orgSlug={orgSlug} canManage={canManage} /> : null}
              {tab === "trust" ? <TrustEditor orgId={orgId} canManage={canManage} /> : null}
              {tab === "mine" ? <ForYouPanel orgId={orgId} /> : null}
            </div>
          </>
        ) : null}
      </ScreenBody>
    </div>
  );
}
