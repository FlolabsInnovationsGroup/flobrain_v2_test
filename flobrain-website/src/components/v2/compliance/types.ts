export type CheckStatus = "pass" | "fail" | "manual" | "not_applicable";
export type Framework = "soc2" | "iso27001";

export type Evidence = { label: string; value: string; link?: string };

export type CheckResult = { key: string; title: string; status: CheckStatus; summary: string; evidence: Evidence[] };

export type Counts = Record<CheckStatus, number> & { total: number };

export type FrameworkSummary = {
  framework: Framework;
  name: string;
  short: string;
  counts: Counts;
  readiness: number;
  groups: { group: string; name: string; counts: Counts; readiness: number }[];
};

export type Attestation = {
  status: "pass" | "fail" | "not_applicable";
  note: string;
  evidence_url: string;
  owner: { id: string; name: string } | null;
  by: string;
  at: string;
};

export type Control = {
  framework: Framework;
  id: string;
  group: string;
  group_name: string;
  name: string;
  summary: string;
  checks: string[];
  status: CheckStatus;
  source: "automated" | "attested" | "none";
  check_results: { key: string; status: CheckStatus; title: string }[];
  attestation: Attestation | null;
};

export type Progress = { total: number; decided: number; pending: number; waiting_apply: number; errors: number };

export type Review = {
  id: string;
  name: string;
  period: string;
  reviewer_mode: "team_leads" | "admins";
  status: "draft" | "open" | "completed" | "cancelled";
  due_at: string | null;
  created_at: string;
  completed_at: string | null;
  created_by: string;
  progress: Progress;
};

export type ItemKind = "membership" | "grant" | "integration" | "buddy";
export type Decision = "pending" | "keep" | "revoke" | "change";

export type ReviewItem = {
  id: string;
  subject: { id: string; name: string; email: string };
  kind: ItemKind;
  label: string;
  details: Record<string, unknown>;
  reviewer: { id: string; name: string } | null;
  decision: Decision;
  change_to: Record<string, unknown>;
  note: string;
  decided_by: string;
  decided_at: string | null;
  applied_at: string | null;
  apply_error: string;
  can_decide: boolean;
};

export type ReviewDetail = Review & { items: ReviewItem[]; grant_days: number[] };

export type ReviewReport = {
  review: { id: string; name: string; period: string; status: string; created_at: string; completed_at: string | null };
  progress: Progress;
  by_kind: Record<string, Record<Decision, number>>;
  changes: { subject: string; kind: string; label: string; decision: Decision; decided_by: string; applied_at: string | null; note: string }[];
  reviewers: string[];
};

export type EvidencePackage = {
  id: string;
  status: "building" | "ready" | "failed" | "expired";
  period_start: string;
  period_end: string;
  size_bytes: number;
  sha256: string;
  files: { path: string; bytes: number; sha256: string }[];
  created_at: string;
  expires_at: string | null;
  created_by: string;
  error: string;
};

export type PolicyTemplate = { key: string; title: string; description: string; installed: boolean };

export type PolicyRow = {
  id: string;
  template: string;
  title: string;
  document_id: string | null;
  room_id: string | null;
  requires_ack: boolean;
  version: number | null;
  sha256: string | null;
  published_at: string | null;
  draft_changed: boolean;
  stats: { acknowledged: number; members: number; missing_ids?: string[] };
};

export type MyPolicy = { id: string; title: string; version: number; sha256: string; published_at: string; body: string; acknowledged_at: string | null };

export type Subprocessor = { name: string; purpose: string; location: string; website: string };
export type TrustDocument = { key: string; title: string; description: string };
export type TrustSection = "overview" | "controls" | "subprocessors" | "data_location" | "documents";

export type TrustPublic = {
  org: { name: string };
  slug: string;
  headline: string;
  sections: TrustSection[];
  disclaimer: string;
  updated_at: string | null;
  overview?: string;
  controls?: { framework: Framework; name: string; readiness: number; passing: number; applicable: number; groups: { name: string; readiness: number }[] }[];
  subprocessors?: Subprocessor[];
  data_location?: string;
  documents?: TrustDocument[];
};

export type TrustSettings = {
  slug: string;
  published: boolean;
  published_at: string | null;
  sections: TrustSection[];
  all_sections: TrustSection[];
  headline: string;
  overview: string;
  subprocessors: Subprocessor[];
  data_location: string;
  documents: TrustDocument[];
  contact_email: string;
  updated_at: string | null;
  path: string;
  example?: { headline: string; overview: string; subprocessors: Subprocessor[]; data_location: string; documents: TrustDocument[]; sections: TrustSection[] };
  preview: TrustPublic;
};

export type TrustRequest = {
  id: string;
  name: string;
  email: string;
  company: string;
  documents: string[];
  message: string;
  status: "new" | "sent" | "declined";
  created_at: string;
  handled_at: string | null;
  handled_by: string;
};

export type Overview = {
  frameworks: FrameworkSummary[];
  checks: CheckResult[];
  open_review: Review | null;
  last_evidence: EvidencePackage | null;
  policies: number;
  trust_published: boolean;
  disclaimer: string;
};

export type Me = { can_view: boolean; can_manage: boolean; review_items: number; policies_to_read: number };
