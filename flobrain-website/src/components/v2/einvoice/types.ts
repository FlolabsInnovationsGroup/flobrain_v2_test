export type Country = "SA" | "EG";
export type InvoiceStatus = "draft" | "ready" | "submitted" | "accepted" | "rejected" | "error";
export type InvoiceType = "standard" | "simplified" | "b2b" | "b2c";
export type Kind = "invoice" | "credit" | "debit";

export type Line = {
  position?: number;
  description: string;
  quantity: string;
  unit_price: string;
  discount: string;
  vat_category: string;
  vat_rate: string;
  exemption_code?: string;
  exemption_reason?: string;
  item_code?: string;
  item_type?: string;
  unit_code?: string;
  net_amount?: string;
  vat_amount?: string;
  total_amount?: string;
};

export type Approval = { id: string; summary: string; expires_at: string; user: string };

export type InvoiceRow = {
  id: string;
  country: Country;
  invoice_type: InvoiceType;
  kind: Kind;
  number: string;
  currency: string;
  issue_datetime: string;
  buyer_name: string;
  tax_total: string;
  total: string;
  status: InvoiceStatus;
  authority_status: string;
  simulated: boolean;
  source: string;
  waiting_approval: boolean;
  approval: Approval | null;
  created_at: string;
  submitted_at: string | null;
};

export type AuthorityMessage = { type?: string; code?: string; category?: string; message?: string; status?: string };

export type Invoice = InvoiceRow & {
  exchange_rate: string | null;
  supply_date: string | null;
  payment_means: string;
  billing_reference: string;
  adjustment_reason: string;
  note: string;
  buyer_tax_number: string;
  buyer_registration_scheme: string;
  buyer_registration_id: string;
  buyer_street: string;
  buyer_building_number: string;
  buyer_district: string;
  buyer_city: string;
  buyer_region: string;
  buyer_postal_code: string;
  buyer_country: string;
  lines: Line[];
  totals: { line_extension: string; discount_total: string; tax_exclusive: string; tax_total: string; tax_inclusive: string; payable: string; breakdown: { category: string; rate: string | null; taxable: string; tax: string; exemption_code?: string }[] };
  icv: number | null;
  pih: string;
  invoice_hash: string;
  qr: string;
  qr_fields: Record<string, string>;
  has_xml: boolean;
  has_cleared_xml: boolean;
  eta_ready: boolean;
  eta_signed: boolean;
  eta_signature_simulated: boolean;
  authority_uuid: string;
  authority_submission: string;
  authority_long_id: string;
  authority_response: {
    mode?: string;
    http_status?: number;
    warnings?: boolean;
    status?: string;
    errorMessages?: AuthorityMessage[];
    warningMessages?: AuthorityMessage[];
    infoMessages?: AuthorityMessage[];
    rejected?: { internalId: string; error: { code?: string; message?: string; details?: { code?: string; message?: string }[] } }[];
    error?: string | { code?: string; message?: string } | null;
    overall_status?: string;
  };
  prepared_at: string | null;
  decided_at: string | null;
  events: { action: string; http_status: number | null; outcome: string; simulated: boolean; at: string }[];
  seller: { name: string; name_ar: string; tax_number: string; registration_id: string; address: string };
  blocker: string;
  signer_mode: "" | "external" | "manual";
};

export type Profile = {
  country: Country;
  environment: string;
  seller_name: string;
  seller_name_ar: string;
  tax_number: string;
  registration_scheme: string;
  registration_id: string;
  street: string;
  building_number: string;
  district: string;
  city: string;
  region: string;
  postal_code: string;
  activity_code: string;
  simulated: boolean;
  updated_at: string;
  // SA
  egs_serial?: string;
  egs_common_name?: string;
  branch_name?: string;
  functionality_map?: string;
  egs_location?: string;
  industry?: string;
  onboarding?: "none" | "key_ready" | "compliance_csid" | "checks_passed" | "production";
  onboarding_error?: string;
  has_key?: boolean;
  csr_ready?: boolean;
  compliance_results?: { type: string; kind: string; http_status: number; ok: boolean; status: string; errorMessages?: AuthorityMessage[] }[];
  certificate_expires_at?: string | null;
  invoice_counter?: number;
  // EG
  client_id_set?: boolean;
  client_id_hint?: string;
  client_secret_set?: boolean;
  client_secret_hint?: string;
  signer_mode?: "external" | "manual";
  signer_url?: string;
  signer_token_set?: boolean;
  signer_token_hint?: string;
};

export type Meta = {
  can_issue: boolean;
  can_manage: boolean;
  is_admin: boolean;
  profiles: { SA: Profile | null; EG: Profile | null };
  chain: { ok: boolean; count: number; broken_at?: string };
  secrets_available: boolean;
  demo: boolean;
  sa_categories: string[];
  eg_subtypes: string[];
  environments: { SA: string[]; EG: string[] };
};

export type ResidencyRow = { class: string; where: string; region: string; status: "ok" | "mismatch" | "unknown" | "not_configured" | "blocked"; note: string };
export type Residency = {
  region: string;
  pinned: boolean;
  regions: { code: string; name: string }[];
  deployment_region: string;
  classes: ResidencyRow[];
  mismatches: string[];
  allowed_ai_hosts: string[];
  can_change: boolean;
};
