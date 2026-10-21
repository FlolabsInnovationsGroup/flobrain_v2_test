"""E-invoicing models: Saudi ZATCA (Fatoora) and Egypt ETA.

- ``TaxProfile``: one per org and country. The seller's registration details, the authority
  environment, the ZATCA onboarding state (EGS key, CSR, compliance and production CSIDs) or the
  ETA client credentials and signer settings, and the Saudi invoice counter and hash chain.
  Secrets (EGS private key, CSID secrets, ETA client secret, signer token) are AES-256-GCM
  ciphertext from ``integrations.crypto`` bound to the profile id, the org and the field name.
  They are never serialized; APIs return a 4-character hint at most.
- ``Invoice`` and ``InvoiceLine``: the document, with every total computed on the server
  (``einvoice.money``). Once an invoice is ``ready`` it is frozen: the counter, previous hash,
  XML or ETA document are fixed and edits are refused. A correction is a new invoice or a note.
- ``AuthorityEvent``: what we sent and what the authority answered (statuses and messages, never
  credentials), for the invoice view and the audit trail.
"""

import uuid

from django.db import models
from django.utils import timezone

SA, EG = "SA", "EG"
COUNTRIES = [(SA, "Saudi Arabia (ZATCA)"), (EG, "Egypt (ETA)")]


class TaxProfile(models.Model):
    # ZATCA environments (base URLs in einvoice.zatca.api) and ETA environments (einvoice.eta.api).
    ENV_SANDBOX, ENV_SIMULATION, ENV_PRODUCTION, ENV_PREPROD = "sandbox", "simulation", "production", "preprod"
    ENVIRONMENTS = [
        (ENV_SANDBOX, "ZATCA developer portal (sandbox)"),
        (ENV_SIMULATION, "ZATCA simulation"),
        (ENV_PREPROD, "ETA pre-production"),
        (ENV_PRODUCTION, "Production"),
    ]
    # ZATCA onboarding steps.
    ONB_NONE, ONB_KEY, ONB_COMPLIANCE, ONB_CHECKED, ONB_PRODUCTION = "none", "key_ready", "compliance_csid", "checks_passed", "production"
    ONBOARDING = [
        (ONB_NONE, "Not started"),
        (ONB_KEY, "Key and CSR ready"),
        (ONB_COMPLIANCE, "Compliance CSID received"),
        (ONB_CHECKED, "Compliance checks passed"),
        (ONB_PRODUCTION, "Production CSID received"),
    ]
    SIGNER_EXTERNAL, SIGNER_MANUAL = "external", "manual"
    SIGNER_MODES = [(SIGNER_EXTERNAL, "On-premises signer service"), (SIGNER_MANUAL, "Manual (export, sign, upload)")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="tax_profiles")
    country = models.CharField(max_length=2, choices=COUNTRIES)
    environment = models.CharField(max_length=12, choices=ENVIRONMENTS, default=ENV_SANDBOX)

    # Seller (both countries). SA: 15-digit VAT number; EG: 9-digit tax registration number.
    seller_name = models.CharField(max_length=200, blank=True, default="")
    seller_name_ar = models.CharField(max_length=200, blank=True, default="")
    tax_number = models.CharField(max_length=20, blank=True, default="")
    # SA: commercial registration (scheme CRN) or another KSA scheme; EG: branch id ("0" for one branch).
    registration_scheme = models.CharField(max_length=8, blank=True, default="CRN")
    registration_id = models.CharField(max_length=40, blank=True, default="")
    street = models.CharField(max_length=200, blank=True, default="")
    building_number = models.CharField(max_length=20, blank=True, default="")
    district = models.CharField(max_length=120, blank=True, default="")  # SA city subdivision
    city = models.CharField(max_length=120, blank=True, default="")
    region = models.CharField(max_length=120, blank=True, default="")  # EG governate
    postal_code = models.CharField(max_length=10, blank=True, default="")
    activity_code = models.CharField(max_length=8, blank=True, default="")  # EG taxpayer activity code

    # ZATCA EGS unit (CSR fields; see einvoice.zatca.crypto.build_csr).
    egs_serial = models.CharField(max_length=200, blank=True, default="")
    egs_common_name = models.CharField(max_length=64, blank=True, default="")
    branch_name = models.CharField(max_length=120, blank=True, default="")
    functionality_map = models.CharField(max_length=4, blank=True, default="1100")
    egs_location = models.CharField(max_length=120, blank=True, default="")
    industry = models.CharField(max_length=120, blank=True, default="")
    onboarding = models.CharField(max_length=16, choices=ONBOARDING, default=ONB_NONE)
    private_key_ciphertext = models.BinaryField(null=True, blank=True)
    csr_pem = models.TextField(blank=True, default="")  # public
    compliance_request_id = models.CharField(max_length=40, blank=True, default="")
    compliance_ciphertext = models.BinaryField(null=True, blank=True)  # {"token","secret"} JSON
    production_ciphertext = models.BinaryField(null=True, blank=True)  # {"token","secret"} JSON
    certificate_b64 = models.TextField(blank=True, default="")  # the CSID certificate in use (public)
    certificate_expires_at = models.DateTimeField(null=True, blank=True)
    compliance_results = models.JSONField(default=list, blank=True)
    onboarding_error = models.CharField(max_length=300, blank=True, default="")

    # Saudi counter and hash chain: the last ICV used and the hash of the last generated document.
    icv_counter = models.PositiveBigIntegerField(default=0)
    last_hash = models.CharField(max_length=100, blank=True, default="")

    # ETA.
    client_id = models.CharField(max_length=100, blank=True, default="")
    client_secret_ciphertext = models.BinaryField(null=True, blank=True)
    client_secret_hint = models.CharField(max_length=4, blank=True, default="")
    signer_mode = models.CharField(max_length=10, choices=SIGNER_MODES, default=SIGNER_MANUAL)
    signer_url = models.CharField(max_length=300, blank=True, default="")
    signer_token_ciphertext = models.BinaryField(null=True, blank=True)
    signer_token_hint = models.CharField(max_length=4, blank=True, default="")

    key_version = models.PositiveSmallIntegerField(default=1)
    # Demo workspace only: simulated onboarding and authority answers, never any network.
    demo = models.BooleanField(default=False)
    updated_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "einvoice_tax_profiles"
        constraints = [models.UniqueConstraint(fields=["org", "country"], name="unique_einvoice_profile")]

    # --- secrets -------------------------------------------------------------------------
    def _aad(self, part: str) -> str:
        return f"einvoice:{self.id}:{part}"

    def set_secret(self, field: str, value: str | None) -> None:
        from integrations import crypto

        setattr(self, f"{field}_ciphertext", crypto.encrypt(value, self._aad(field), self.org_id) if value else None)
        self.key_version = crypto.current_key_version()

    def secret(self, field: str) -> str:
        from integrations import crypto

        blob = getattr(self, f"{field}_ciphertext")
        if not blob:
            return ""
        return crypto.decrypt(blob, self._aad(field), self.org_id, self.key_version)

    def has_secret(self, field: str) -> bool:
        return bool(getattr(self, f"{field}_ciphertext"))

    def __repr__(self):  # never secrets
        return f"<TaxProfile {self.country} {self.environment} {self.onboarding}>"

    __str__ = __repr__


class Invoice(models.Model):
    DRAFT, READY, SUBMITTED, ACCEPTED, REJECTED, ERROR = "draft", "ready", "submitted", "accepted", "rejected", "error"
    STATUSES = [
        (DRAFT, "Draft"),
        (READY, "Ready to send"),
        (SUBMITTED, "Submitted"),
        (ACCEPTED, "Accepted"),
        (REJECTED, "Rejected"),
        (ERROR, "Error"),
    ]
    # SA: standard (B2B, cleared) or simplified (B2C, reported). EG: b2b or b2c (receiver type B or P).
    STANDARD, SIMPLIFIED, B2B, B2C = "standard", "simplified", "b2b", "b2c"
    TYPES = [(STANDARD, "Standard tax invoice"), (SIMPLIFIED, "Simplified tax invoice"), (B2B, "Business"), (B2C, "Consumer")]
    INVOICE, CREDIT, DEBIT = "invoice", "credit", "debit"
    KINDS = [(INVOICE, "Invoice"), (CREDIT, "Credit note"), (DEBIT, "Debit note")]
    SOURCES = [("manual", "Created here"), ("odoo", "Odoo"), ("zoho", "Zoho Books"), ("buddy", "Buddy"), ("demo", "Demo")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)  # also the ZATCA cbc:UUID
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="einvoices")
    country = models.CharField(max_length=2, choices=COUNTRIES)
    invoice_type = models.CharField(max_length=10, choices=TYPES)
    kind = models.CharField(max_length=7, choices=KINDS, default=INVOICE)
    number = models.CharField(max_length=50)
    currency = models.CharField(max_length=3)
    exchange_rate = models.DecimalField(max_digits=18, decimal_places=5, null=True, blank=True)  # EG: EGP per unit
    issue_datetime = models.DateTimeField(default=timezone.now)
    supply_date = models.DateField(null=True, blank=True)
    payment_means = models.CharField(max_length=4, blank=True, default="10")  # UN/ECE 4461 (10 = cash)
    billing_reference = models.CharField(max_length=50, blank=True, default="")  # original invoice for notes
    adjustment_reason = models.CharField(max_length=300, blank=True, default="")  # reason for notes (KSA-10)
    note = models.CharField(max_length=500, blank=True, default="")

    buyer_name = models.CharField(max_length=200, blank=True, default="")
    buyer_tax_number = models.CharField(max_length=20, blank=True, default="")
    buyer_registration_scheme = models.CharField(max_length=8, blank=True, default="")
    buyer_registration_id = models.CharField(max_length=40, blank=True, default="")
    buyer_street = models.CharField(max_length=200, blank=True, default="")
    buyer_building_number = models.CharField(max_length=20, blank=True, default="")
    buyer_district = models.CharField(max_length=120, blank=True, default="")
    buyer_city = models.CharField(max_length=120, blank=True, default="")
    buyer_region = models.CharField(max_length=120, blank=True, default="")
    buyer_postal_code = models.CharField(max_length=10, blank=True, default="")
    buyer_country = models.CharField(max_length=2, blank=True, default="")

    # Totals, always computed by einvoice.money (never taken from the client).
    line_extension = models.DecimalField(max_digits=20, decimal_places=5, default=0)
    discount_total = models.DecimalField(max_digits=20, decimal_places=5, default=0)
    tax_exclusive = models.DecimalField(max_digits=20, decimal_places=5, default=0)
    tax_total = models.DecimalField(max_digits=20, decimal_places=5, default=0)
    tax_inclusive = models.DecimalField(max_digits=20, decimal_places=5, default=0)
    payable = models.DecimalField(max_digits=20, decimal_places=5, default=0)
    tax_breakdown = models.JSONField(default=list, blank=True)

    status = models.CharField(max_length=10, choices=STATUSES, default=DRAFT, db_index=True)
    source = models.CharField(max_length=8, choices=SOURCES, default="manual")
    source_ref = models.CharField(max_length=80, blank=True, default="")

    # SA, fixed at "ready": counter, previous hash, this document's hash, QR and the signed XML.
    icv = models.PositiveBigIntegerField(null=True, blank=True)
    pih = models.CharField(max_length=100, blank=True, default="")
    invoice_hash = models.CharField(max_length=100, blank=True, default="")
    qr = models.TextField(blank=True, default="")
    xml = models.TextField(blank=True, default="")
    # EG, fixed at "ready": the document JSON exactly as it will be sent (without signatures) and
    # the issuer's CAdES-BES signature from the customer's token (never made by FloBrain).
    eta_document = models.TextField(blank=True, default="")
    eta_signature = models.TextField(blank=True, default="")
    eta_signature_simulated = models.BooleanField(default=False)

    authority_uuid = models.CharField(max_length=80, blank=True, default="")  # ETA document uuid
    authority_submission = models.CharField(max_length=80, blank=True, default="")  # ETA submission uuid
    authority_long_id = models.CharField(max_length=80, blank=True, default="")
    authority_status = models.CharField(max_length=40, blank=True, default="")
    authority_response = models.JSONField(default=dict, blank=True)
    cleared_xml = models.TextField(blank=True, default="")  # SA clearance: the invoice ZATCA stamped
    simulated = models.BooleanField(default=False)

    proposal = models.ForeignKey("actions.ActionProposal", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="+")
    prepared_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "einvoice_invoices"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["org", "country", "status"], name="einvoice_list")]
        constraints = [
            models.UniqueConstraint(fields=["org", "country", "number"], name="unique_einvoice_number"),
            models.UniqueConstraint(fields=["org", "country", "icv"], condition=models.Q(icv__isnull=False), name="unique_einvoice_icv"),
        ]


class InvoiceLine(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")
    position = models.PositiveSmallIntegerField()
    description = models.CharField(max_length=300)
    item_code = models.CharField(max_length=100, blank=True, default="")  # EG: GS1 or EGS code
    item_type = models.CharField(max_length=3, blank=True, default="")  # EG: GS1 | EGS
    unit_code = models.CharField(max_length=10, blank=True, default="")  # SA: UN/ECE rec 20; EG: ETA unit type
    quantity = models.DecimalField(max_digits=18, decimal_places=6)
    unit_price = models.DecimalField(max_digits=18, decimal_places=5)
    discount = models.DecimalField(max_digits=18, decimal_places=5, default=0)
    vat_category = models.CharField(max_length=4)  # SA: S|Z|E|O; EG: T1 subtype (V001..V010)
    vat_rate = models.DecimalField(max_digits=6, decimal_places=2)
    exemption_code = models.CharField(max_length=30, blank=True, default="")
    exemption_reason = models.CharField(max_length=200, blank=True, default="")
    # Computed.
    gross_amount = models.DecimalField(max_digits=20, decimal_places=5, default=0)
    net_amount = models.DecimalField(max_digits=20, decimal_places=5, default=0)
    vat_amount = models.DecimalField(max_digits=20, decimal_places=5, default=0)
    total_amount = models.DecimalField(max_digits=20, decimal_places=5, default=0)

    class Meta:
        db_table = "einvoice_lines"
        ordering = ["position"]
        constraints = [models.UniqueConstraint(fields=["invoice", "position"], name="unique_einvoice_line")]


class AuthorityEvent(models.Model):
    """One exchange with ZATCA or ETA, or a step of onboarding. Payloads never hold credentials."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, null=True, blank=True, related_name="events")
    country = models.CharField(max_length=2, choices=COUNTRIES)
    action = models.CharField(max_length=40)  # clearance | reporting | compliance_csid | submit | poll | ...
    http_status = models.PositiveSmallIntegerField(null=True, blank=True)
    outcome = models.CharField(max_length=40, blank=True, default="")
    response = models.JSONField(default=dict, blank=True)
    simulated = models.BooleanField(default=False)
    actor = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "einvoice_events"
        ordering = ["-created_at"]
