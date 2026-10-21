# E-invoicing (Saudi ZATCA, Egypt ETA) and data residency

Workstream M3 (growth round 2, 2026-10-21). Backend app `einvoice`, screen `/w/[org]/einvoices`, phrase area `einvoice`.

## What it does

- **Invoices for two authorities.** A draft has a country (`SA` or `EG`), a type (SA: standard or simplified; EG: business or consumer), seller details from the org's tax profile, buyer details, lines (quantity, unit price, discount, VAT category and rate) and server-computed totals. Saudi drafts can also be credit or debit notes.
- **Three ways to start a draft:** from scratch, from an Odoo or Zoho Books invoice read through the write-back connection (`integrations.write`), or from a buddy with the `einvoice.prepare` tool (approval required; it only creates a draft).
- **Prepare** freezes a draft:
  - SA: next invoice counter (ICV), previous invoice hash (PIH), UBL 2.1 XML, invoice hash, ECDSA signature in a XAdES block, QR code (tags 1 to 9; tag 9 for simplified documents only).
  - EG: the ETA document JSON (type `I`, version `1.0`) and its canonical serialization, ready to be signed by the customer's token.
- **Send** creates an approval (`einvoice.submit`, risk `external`). Only after the person approves does FloBrain call ZATCA (clearance for standard, reporting for simplified) or the ETA (token, submission; then status polling). The authority's answer is stored on the invoice: status, codes and messages, the cleared XML (SA), the ETA uuid and submission id (EG).
- **ZATCA onboarding wizard** (Settings tab): key and CSR, compliance CSID with the portal OTP, compliance checks (sample invoice, credit and debit note for each type the unit is set up for), production CSID, reset.
- **ETA settings:** client id and secret (secret write-only, masked), environment, who signs: an on-premises signer service (allowlisted URL, bearer token, mTLS-ready) or manual (download the text to sign, upload the signature).
- **Print view:** bilingual Arabic and English tax invoice with the QR, right to left in Arabic, printable to PDF from the browser.
- **Data residency:** the org chooses a data region (`sa`, `ae`, `eg`, `eu`, `us`) and may pin it; a report shows where each kind of data lives and flags mismatches; `einvoice.residency.allowed_ai_host(org, host)` refuses AI hosts outside a pinned region (enforcement needs one shared hook, below).

## Flag and permissions

- Flag `einvoice` (off by default, on in the demo). Off: every endpoint answers 501 `not_implemented`, tools are not offered and refuse in `check`.
- `einvoice.view`: list and read invoices, the residency report, the meta summary.
- `einvoice.issue`: create, edit, delete own drafts, import, prepare, request sending, decide your own approval, upload a signature, poll.
- `einvoice.manage`: tax profiles, ZATCA onboarding, ETA credentials and signer, residency changes (also needs org owner or admin).
- Approvals follow `actions`: the person who asked to send approves or rejects it (24 hours). The invoice page shows the approval in amber; the approvals inbox shows it too.

## Endpoints

All under `/api/v2`, `org` is the org uuid.

| Method | Path | Permission |
|---|---|---|
| GET | `orgs/{org}/einvoice/meta` | view |
| PUT | `orgs/{org}/einvoice/settings/{SA\|EG}` | manage |
| POST | `orgs/{org}/einvoice/zatca/{key\|compliance\|checks\|production\|reset}` | manage |
| GET | `orgs/{org}/einvoice/zatca/csr` | manage |
| POST | `orgs/{org}/einvoice/eta/check` | manage |
| GET, PATCH | `orgs/{org}/einvoice/residency` | view, manage + owner/admin |
| GET, POST | `orgs/{org}/einvoices` (`?country=&status=`) | view, issue |
| POST | `orgs/{org}/einvoices/import` `{provider, ref, country, invoice_type}` | issue |
| GET, PATCH, DELETE | `orgs/{org}/einvoices/{id}` | view, issue |
| POST | `orgs/{org}/einvoices/{id}/{prepare\|submit\|poll\|copy}` | issue |
| POST | `orgs/{org}/einvoices/{id}/approval/{approve\|reject}` | issue (proposer only) |
| GET | `orgs/{org}/einvoices/{id}/xml` (`?cleared=1`) | view |
| GET | `orgs/{org}/einvoices/{id}/eta-document` | issue |
| POST | `orgs/{org}/einvoices/{id}/signature` `{signature}` | issue |

Buddy tools: `einvoice.prepare` (write) and `einvoice.submit` (external), both `einvoice.issue`, flag `einvoice`, registered with `actions.plugins.register_tool` from `EinvoiceConfig.ready()`.

## Models (migration `einvoice/0001_initial`)

- `TaxProfile` (one per org and country): seller registration and address, environment, EGS fields, onboarding state, encrypted EGS private key, compliance and production CSIDs (token and secret, encrypted), the certificate in use (public), compliance check results, the Saudi counter (`icv_counter`) and last hash (`last_hash`), ETA client id, encrypted client secret and signer token, signer mode and URL, `demo`.
- `Invoice`: header, buyer, totals (computed), status `draft | ready | submitted | accepted | rejected | error`, source, SA `icv`, `pih`, `invoice_hash`, `qr`, `xml`, `cleared_xml`; EG `eta_document`, `eta_signature`; authority ids, status and response; link to the pending approval.
- `InvoiceLine`: description, item code and type (EG), unit, quantity, unit price, discount, VAT category and rate, exemption code and reason, computed gross, net, VAT and total.
- `AuthorityEvent`: each exchange with an authority or onboarding step (status, outcome, trimmed messages; never credentials).

## Totals and rounding

Server-side, `Decimal` only (`einvoice/money.py`); the form shows the same numbers with exact BigInt arithmetic (`src/components/v2/einvoice/money.ts`), but the server's are the ones stored.

- **Saudi Arabia**, from the ZATCA XML Implementation Standard [Z2] (EN 16931 rules it adopts): 2 decimals, half up, only final results rounded. Line net (BT-131) = quantity x price - line allowance; line VAT (KSA-11) = net x rate; line amount with VAT (KSA-12) = net + VAT. VAT per category (BR-CO-17, BR-S-09) = taxable amount x rate, rounded once; document VAT (BT-110) is the sum of the category amounts, not of the line amounts. BT-109 = BT-106 (no document-level allowances here), BT-112 = BT-109 + BT-110, payable = BT-112. Categories S, Z, E, O; Z, E and O need a `VATEX-SA-…` exemption code and have a 0% rate; S has none (BR-S-10). Only SAR invoices (BT-111 must be the VAT in SAR).
- **Egypt**, from the ETA SDK invoice v1.0 page [E3]: up to 5 decimals. salesTotal = quantity x unit value in EGP (a foreign price is converted with the exchange rate and rounded to 5 decimals, the `amountEGP` rule); netTotal = salesTotal - discount; T1 = netTotal x rate; line total = netTotal + T1; totalSalesAmount, totalDiscountAmount, netAmount = sales - discount, taxTotals (T1 = sum of lines), totalAmount = netAmount + taxes. T1 subtypes V001 to V010 [E4]. Other tax types (T2 to T20), value difference, taxable fees, items discount and the extra discount are not modelled (sent as 0).

## Saudi ZATCA details

- **XML** (`einvoice/zatca/ubl.py`): UBL 2.1 `Invoice`, `ProfileID reporting:1.0`, `InvoiceTypeCode` 388/381/383 with `@name` `0100000` (standard) or `0200000` (simplified) [Z2], `ICV`, `PIH` and `QR` additional document references, `cac:Signature`, seller (CRN scheme, national address, VAT), buyer, delivery date (supply date, required for standard), payment means (and the note reason as `InstructionNote`), two `TaxTotal` blocks, `LegalMonetaryTotal`, lines with KSA-11 and KSA-12. Written without indentation so removing elements for hashing leaves no whitespace differences.
- **Hash** [Z3][Z5]: remove `ext:UBLExtensions`, `cac:Signature` and the `QR` reference, canonicalize (C14N 1.1; for this document lxml's C14N 1.0 output is identical because there are no `xml:id`/`xml:base` attributes), SHA-256, Base64 of the raw digest. First PIH: Base64 of the hex SHA-256 of "0" (`NWZlY2Vi…OQ==`, as in ZATCA's SDK samples).
- **Signature block** [Z5]: SignatureValue = ECDSA (SHA-256) over the 32 hash bytes; certificate digest and SignedProperties digest are Base64 of the *hex* SHA-256 (ZATCA-specific). SignedProperties is written as its exclusive canonical form so a validator that hashes the text and one that canonicalizes get the same digest.
- **QR** [Z1][Z3]: TLV with one-byte lengths, Base64, at most 700 characters. Tags 1 to 5 UTF-8 text; 6 hash and 7 signature as Base64 text (configurable, see below); 8 DER public key; 9 the certificate's signature (simplified only).
- **Keys and CSR** [Z3][Z6]: secp256k1 via `cryptography`; subject C, OU, O, CN; certificateTemplateName (1.3.6.1.4.1.311.20.2) `TSTZATCA-Code-Signing` / `PREZATCA-Code-Signing` / `ZATCA-Code-Signing` [Z4]; SAN dirName SN (EGS serial `1-…|2-…|3-…`), UID (VAT number), title (functionality map, e.g. 1100), registeredAddress, businessCategory. Sent as Base64 of the PEM [Z6].
- **API** [Z4][Z7]: base URLs `https://gw-fatoora.zatca.gov.sa/e-invoicing/{developer-portal|simulation|core}`; `POST /compliance` (OTP header), `/compliance/invoices`, `/production/csids`, `/invoices/clearance/single` (`Clearance-Status: 1`), `/invoices/reporting/single`; `Accept-Version: V2`, `Accept-Language: en`, Basic auth `binarySecurityToken:secret`. 200 accepted, 202 accepted with warnings, 400 rejected.
- **Chain rules** [Z1]: counters are never reused, a rejected document keeps its counter and hash (the chain continues through it), a correction is a new document. FloBrain freezes prepared invoices and offers "Copy to a new draft". `GET meta` reports whether the chain is intact.
- **Compliance checks** use their own temporary counter and chain, so the production chain starts clean.

## Egypt ETA details

- **Document** (`einvoice/eta/document.py`) per [E3]: issuer type B with branchID, receiver B / P / F (F when the buyer country is not EG), `dateTimeIssued` in UTC, lines with `itemType` GS1/EGS, `itemCode`, `unitType`, `unitValue`, `salesTotal`, `discount`, `netTotal`, `taxableItems` (T1), `total`, totals. A discount is sent as an amount only (if rate and amount are both given the ETA checks they match).
- **Canonical serialization** (`einvoice/eta/serialize.py`) per [E1]: property names upper-cased and quoted, simple values quoted exactly as written, arrays as the name once then the name before each element, `signatures` left out. We write the JSON ourselves so numbers keep the exact text the canonical form uses, and refuse double quotes, backslashes and line breaks in text fields (the SDK leaves open whether escaped or plain text is serialized). Tested against fragments of the SDK's own serialized sample [E2].
- **Signing**: never by FloBrain. CAdES-BES with the taxpayer's eSeal on a USB token or HSM [E5][E9]. `external` mode POSTs `{internal_id, canonical_b64, sha256}` to the customer's signer and expects `{signature}`; `manual` mode exports the text and accepts an uploaded signature. We only check that it is a CMS SignedData structure; the ETA verifies it.
- **API** [E6][E7][E8][E9]: token `POST https://id[.preprod].eta.gov.eg/connect/token` (client credentials, scope `InvoicingAPI`), `POST https://api[.preprod].invoicing.eta.gov.eg/api/v1.0/documentsubmissions/` with `{"documents": [...]}` (202 with accepted and rejected documents; 422 duplicate within 10 minutes), `GET …/documentsubmissions/{uuid}?pageNo=1&pageSize=10` for `valid | invalid | rejected | cancelled | submitted`.

## Data residency and PDPL

- Org setting: `org.settings["data_region"] = {"region": "sa", "pinned": true}` (owner or admin with `einvoice.manage`, audited).
- Report (`GET …/einvoice/residency`): database and backups (`DATA_REGION_DATABASE` or `DATA_REGION_DEPLOYMENT`), files (`CONTENT_STORAGE`, `CONTENT_S3_REGION` mapped from cloud region codes, or `DATA_REGION_FILES`), AI model (`AI_DIRECT_BASE_URL`), legacy AI (`MULTIMODAL_SERVICE_URL`), embeddings (`EMBEDDINGS_BASE_URL`), transcription (`ASR_BASE_URL`). A host's region comes from `DATA_REGION_HOSTS` (`host=sa,…`) or from `AI_SELF_HOSTED_HOSTS` (deployment region). Unknown stays unknown; it is never guessed.
- `allowed_ai_host(org, host)`: unpinned orgs are not restricted here; pinned orgs may use hosts in `DATA_REGION_AI_HOSTS_<REGION>` or hosts whose known region is the pinned one. An empty host (demo model, test fake) is allowed.
- **Shared hook still needed** (brain/llm is shared, not edited here). In `brain/llm/policy.py`, at the top of `check_ai`:

  ```python
  def check_ai(org, kind, target=None) -> str:
      from einvoice.residency import check_ai_residency

      blocked = check_ai_residency(org, kind, target)
      if blocked:
          return blocked  # "data_region"
      if inference_scope(org) != PRIVATE_ONLY:
          ...
  ```

  Every caller already refuses on a non-empty result. Callers that word the refusal (for example `buddies/chat.py`, which says "only allows self-hosted models") should map `"data_region"` to `einvoice.residency.refusal_message(org)`. Transcription calls (`meetings`, `rooms/voice`) should also call `check_ai_residency(org, "transcription")`.
- **Saudi PDPL** [P1]: enforceable since 14 September 2024 (SDAIA). Transfers outside the Kingdom are allowed under the Transfer Regulation's conditions (adequate country list, or safeguards such as standard contractual clauses, with a risk assessment for some transfers); controller registration and DPO duties apply in listed cases. It is not a blanket localization rule. Separately, the VAT Implementing Regulations (Article 66) keep invoices and records in the Kingdom; electronic records may sit abroad if they are reachable from an access point in the Kingdom [P3].
- **Egypt PDPL** (Law 151 of 2020) [P2]: Executive Regulations issued 1 November 2025 (Ministerial Decision 816/2025), one-year compliance window (plan for 1 November 2026). Cross-border transfers, including to cloud environments abroad, need a licence or permit from the Personal Data Protection Center; controllers and processors need a general licence; a DPO is required. No general localization rule is stated.
- This is product information, not legal advice. Pinning a region and keeping data in-region helps, but each customer decides its transfers with its own counsel.

## Security

- Secrets (EGS private key, CSID tokens and secrets, ETA client secret, signer token) are AES-256-GCM via `integrations.crypto`, bound to the profile id, org and field. Never serialized; the API returns `…` + last 4 at most. Without `CREDENTIALS_ENCRYPTION_KEY` nothing secret can be saved (409).
- Outbound HTTP only through `einvoice/transport.py`: https, port 443, no credentials in URLs, host allowlists (ZATCA host; ETA identity and API hosts; signer hosts only from `EINVOICE_SIGNER_ALLOWED_HOSTS`), public addresses with the connection pinned (`platform_api.net`), no redirects, response size capped. Base URL overrides are still checked against the allowlist. Signer hosts may be private only with `EINVOICE_SIGNER_ALLOW_PRIVATE=True` (self-hosted installs); mTLS with `EINVOICE_SIGNER_CLIENT_CERT`, `EINVOICE_SIGNER_CLIENT_KEY`, `EINVOICE_SIGNER_CA_FILE`.
- Sending to an authority only runs from an approved `einvoice.submit` proposal. Onboarding steps are run by an admin with `einvoice.manage` (the OTP they type is ZATCA's own human step) and are audited.
- Authority answers are trimmed to codes and messages; no tokens or full bodies are stored.

## Demo

`demo/extras/a3_einvoice.py`: "Nile Labs Arabia (demo)" (VAT 300000000000003, fake) onboarded with a self-signed certificate labelled "DEMO - not issued by ZATCA", and "Nile Labs Egypt (demo)" (tax number 100200300, fake, manual signer). Eight invoices: SA cleared, reported, rejected (simulated answer), ready and waiting for approval, draft; EG accepted, submitted (poll turns it accepted), error (signer did not answer). Saudi invoices are really built, hashed, chained, signed and QR-stamped; answers are simulated; EG signatures are a labelled stand-in. The Back office buddy gets `einvoice.prepare` and a preset prompt; the demo model answers it (`brain/llm/demo_handlers/einvoice.py`). Nothing reaches the network. Without `CREDENTIALS_ENCRYPTION_KEY` the Saudi invoices stay drafts.

## What needs real onboarding before production

1. **ZATCA**: the taxpayer's Fatoora portal account; an OTP per EGS unit; a run in the developer portal and then the simulation environment; validating our XML, hash, signature block and QR with ZATCA's SDK (`fatoora -validate`) and the compliance API; the production CSID; renewal before the certificate expires (renewal with `PATCH /production/csids` is not built yet).
2. **ETA**: ERP registration in the taxpayer profile (client id and secrets for pre-production and production), the taxpayer activity code and branch ids, item codes registered as EGS/GS1 on the ETA portal, an eSeal USB token or HSM from an approved issuer, and the on-premises signer service (or the manual flow). Test in pre-production before production.
3. **Operators**: `CREDENTIALS_ENCRYPTION_KEY`; for external signers `EINVOICE_SIGNER_ALLOWED_HOSTS` (and mTLS files); for residency `DATA_REGION_DEPLOYMENT`, `DATA_REGION_HOSTS`, `DATA_REGION_AI_HOSTS_<REGION>`; the shared `check_ai` hook above.
4. **Zoho import** needs the write-back Zoho connection to also request `ZohoBooks.invoices.READ` (owned by the connectors workstream).

## Unverified details, kept configurable

| Detail | What we do | Setting |
|---|---|---|
| QR tags 6 and 7 encoding | Base64 text (as ZATCA's SDK emits); the Security Features standard describes tag 6 as raw bytes | `EINVOICE_ZATCA_QR_HASH_ENCODING=raw` |
| QR tag 3 timestamp | `IssueDate T IssueTime` in Riyadh time, no zone | `EINVOICE_ZATCA_QR_TIME_SUFFIX=Z` |
| CSR in the compliance request | Base64 of the PEM | `EINVOICE_ZATCA_CSR_ENCODING=der_base64` |
| ZATCA base URLs (developer portal path) | as above | `EINVOICE_ZATCA_BASE_SANDBOX`, `_SIMULATION`, `_PRODUCTION` (allowlisted) |
| SignedProperties reference `Type` | xmldsig `SignatureProperties` (SDK samples); the standard names the ETSI type | constant `ubl.SIGNED_PROPERTIES_TYPE` |
| Line discount | line allowance (BG-27) with reason "discount" | code |
| Credit and debit notes | `Invoice` root with 381/383, as in the SDK samples | code |
| Curve | secp256k1 (SDK, OpenSSL guidance); the standard only says 256-bit ECDSA | code |
| ETA token request | client id and secret as form fields; some examples use Basic auth | `EINVOICE_ETA_TOKEN_AUTH=basic` |
| ETA identity and API hosts | `id[.preprod].eta.gov.eg`, `api[.preprod].invoicing.eta.gov.eg` (from secondary sources; the SDK auth page could not be opened here) | `EINVOICE_ETA_ID_*`, `EINVOICE_ETA_API_*` |
| ETA signature field | `{"signatureType": "I", "value": …}` (SDK examples); the invoice page lists it as `type` | code |
| ETA consumer threshold for buyer ID | EGP 50,000 | `EINVOICE_ETA_B2C_ID_THRESHOLD` |
| ETA line tax rounding | each amount to 5 decimals, half up | code |

## Known limits

- SAR only for Saudi invoices; no document-level allowances or charges; no prepayment invoices; no summary, export, third-party, nominal or self-billed flags.
- Egyptian credit and debit notes, export invoices, receipts (e-receipt/POS) and cancellation are not built.
- PDF/A-3 with the XML embedded is not generated; the print view prints to an ordinary PDF.
- Certificate renewal and expiry reminders are not built (`certificate_expires_at` is shown).
- The residency check is enforced only once the shared hook is added.

## Sources

- [Z1] ZATCA, E-invoicing Detailed Technical Guideline: https://zatca.gov.sa/en/E-Invoicing/Introduction/Guidelines/Documents/E-invoicing-Detailed-Technical-Guideline.pdf
- [Z2] ZATCA, Electronic Invoice XML Implementation Standard (2023-05-19): https://zatca.gov.sa/ar/E-Invoicing/SystemsDevelopers/Documents/20230519_ZATCA_Electronic_Invoice_XML_Implementation_Standard_%20vF.pdf
- [Z3] ZATCA, Electronic Invoice Security Features Implementation Standards (2023-05-19): https://zatca.gov.sa/ar/E-Invoicing/SystemsDevelopers/Documents/20230519_ZATCA_Electronic_Invoice_Security_Features_Implementation_Standards_vF.pdf
- [Z4] ZATCA developer community, E-Invoicing API endpoints: https://zatca1.discourse.group/t/e-invoicing-api-endpoints/487
- [Z5] ZATCA developer community, Signing Process: https://zatca1.discourse.group/t/signing-process/354
- [Z6] ZATCA developer community, Invalid CSR for simulation (working OpenSSL CSR config and encoding): https://zatca1.discourse.group/t/invalid-csr-for-simulation/6098
- [Z7] Qoyod, ZATCA API overview (headers; secondary source): https://www.qoyod.com/en/learn/api-overview/
- [Z8] ZATCA developer community, QR code additional tags 6 to 9: https://zatca1.discourse.group/t/qr-code-additional-tags-6-9/1189
- [E1] ETA SDK, Document serialization approach: https://sdk.invoicing.eta.gov.eg/document-serialization-approach/
- [E2] ETA SDK, sample serialized document: https://sdk.invoicing.eta.gov.eg/files/one-doc-serialized.json.txt
- [E3] ETA SDK, Invoice v1.0: https://sdk.invoicing.eta.gov.eg/documents/invoice-v1-0/
- [E4] ETA SDK, Tax types: https://sdk.invoicing.eta.gov.eg/codes/tax-types/
- [E5] ETA SDK, Document signature creation: https://sdk.invoicing.eta.gov.eg/signature-creation/
- [E6] ETA SDK, Submit documents: https://sdk.invoicing.eta.gov.eg/einvoicingapi/01-submit-documents/
- [E7] ETA SDK, Get submission: https://sdk.invoicing.eta.gov.eg/einvoicingapi/09-get-submission/
- [E8] Ecosire, Egypt ETA module docs (production and pre-production hosts; secondary source): https://docs.ecosire.com/odoo-modules/egypt-eta-einvoicing
- [E9] Chilkat, ITIDA sign JSON and send (token request, CAdES-BES attributes; secondary source): https://www.example-code.com/phpExt/itida_egypt_sign_json_and_send.asp
- [E10] Odoo documentation, Egypt localization (USB token signing, item codes, branch and activity codes): https://www.odoo.com/documentation/latest/applications/finance/fiscal_localizations/egypt.html
- [P1] CMS, New SDAIA rules and guidelines, KSA personal data protection framework now enforceable: https://cms.law/en/omn/legal-updates/new-sdaia-rules-and-guidelines-published-as-ksa-s-personal-data-protection-framework-is-now-enforceable
- [P2] CMS, Egypt's PDPL executive regulations issued: https://cms.law/en/are/legal-updates/egypt-s-pdpl-executive-regulations-issued-one-year-compliance-countdown-begins
- [P3] ZATCA developer community, Record keeping related to invoices (VAT Implementing Regulations Article 66): https://zatca1.discourse.group/t/record-keeping-related-to-invoices/2129
