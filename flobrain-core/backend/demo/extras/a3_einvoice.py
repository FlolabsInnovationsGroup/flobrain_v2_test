"""E-invoicing demo: a Saudi branch (ZATCA) and an Egyptian branch (ETA) of Nile Labs, both with
clearly fake registration numbers and simulated onboarding, eight invoices in mixed states and
simulated authority answers. Nothing reaches ZATCA or the ETA.

- Saudi profile: onboarded in the developer-portal environment with a *self-signed demo
  certificate* ("DEMO - not issued by ZATCA"). Invoices are really built, hashed, chained,
  signed and QR-stamped by the same code as production, so the XML, the hash chain and the QR
  are real; the answers are simulated.
- Egyptian profile: pre-production, signer in manual mode, no client secret; the accepted and
  submitted invoices carry a labelled stand-in signature (never a real one).
Without ``CREDENTIALS_ENCRYPTION_KEY`` (needed to store the demo key) the Saudi invoices are kept
as drafts and the onboarding shows "not started".
"""

from datetime import timedelta
from decimal import Decimal

SA_VAT = "300000000000003"  # demo: valid shape, not a real taxpayer
EG_TAX = "100200300"  # demo


def _sa_profile(org, admin, now):
    from einvoice.models import TaxProfile
    from einvoice.zatca import crypto as zcrypto
    from integrations import crypto

    profile = TaxProfile.objects.create(
        org=org, country="SA", environment=TaxProfile.ENV_SANDBOX, demo=True, updated_by=admin,
        seller_name="Nile Labs Arabia (demo)", seller_name_ar="مختبرات النيل العربية (تجريبي)", tax_number=SA_VAT,
        registration_scheme="CRN", registration_id="1010000000", street="King Fahd Road", building_number="2322",
        district="Al Olaya", city="Riyadh", postal_code="12214",
        egs_serial="1-FloBrain|2-2.0|3-7f1c2d9e-demo", egs_common_name="FloBrain-EGS-Riyadh-01", branch_name="Riyadh Branch",
        functionality_map="1100", egs_location="RRRD2322", industry="Software services",
        created_at=now - timedelta(days=30),
    )
    if not crypto.is_configured():
        return profile
    key = zcrypto.generate_key()
    profile.set_secret("private_key", zcrypto.key_to_pem(key))
    profile.csr_pem = zcrypto.build_csr(
        key, environment="sandbox", common_name=profile.egs_common_name, egs_serial=profile.egs_serial, vat_number=SA_VAT,
        branch_name=profile.branch_name, org_name=profile.seller_name, functionality_map="1100", location=profile.egs_location, industry=profile.industry,
    )
    cert = zcrypto.demo_certificate(key, SA_VAT, profile.seller_name)
    profile.certificate_b64 = cert
    profile.certificate_expires_at = zcrypto.load_certificate(cert).not_valid_after_utc
    profile.set_secret("production", '{"token": "demo-not-real", "secret": "demo-not-real"}')
    profile.compliance_request_id = "1234567890123"
    profile.compliance_results = [
        {"type": t, "kind": k, "http_status": 200, "ok": True, "status": "PASS", "errorMessages": [], "warningMessages": [], "infoMessages": []}
        for t in ("standard", "simplified") for k in ("invoice", "credit", "debit")
    ]
    profile.onboarding = TaxProfile.ONB_PRODUCTION
    profile.save()
    return profile


def _eg_profile(org, admin, now):
    from einvoice.models import TaxProfile

    return TaxProfile.objects.create(
        org=org, country="EG", environment=TaxProfile.ENV_PREPROD, demo=True, updated_by=admin,
        seller_name="Nile Labs Egypt (demo)", seller_name_ar="مختبرات النيل مصر (تجريبي)", tax_number=EG_TAX, registration_id="0",
        street="Mohamed Farid Street", building_number="14", city="Nasr City", region="Cairo", postal_code="11765",
        activity_code="6201", client_id="demo-client-id-0000", signer_mode=TaxProfile.SIGNER_MANUAL, created_at=now - timedelta(days=30),
    )


SA_INVOICES = [
    # (days ago, type, buyer, lines, final state)
    (9, "standard", {"buyer_name": "Gulf Retail Co. (demo)", "buyer_tax_number": "311111111100003", "buyer_street": "Prince Sultan Street", "buyer_building_number": "4410", "buyer_district": "Al Rawdah", "buyer_city": "Jeddah", "buyer_postal_code": "23435", "buyer_country": "SA"},
     [("Dashboard setup", "1", "12000.00", "0"), ("Training day", "2", "3500.00", "500.00")], "accepted"),
    (6, "simplified", {"buyer_name": ""}, [("Monthly plan", "3", "149.00", "0"), ("Arabic workbook", "1", "60.00", "0", "Z", "0", "VATEX-SA-EDU", "Educational material")], "accepted"),
    (4, "simplified", {"buyer_name": "Walk-in customer"}, [("Support hours", "5", "220.00", "0")], "rejected"),
    (1, "standard", {"buyer_name": "Najd Logistics (demo)", "buyer_tax_number": "322222222200003", "buyer_street": "Olaya Street", "buyer_building_number": "7788", "buyer_district": "Al Malaz", "buyer_city": "Riyadh", "buyer_postal_code": "12831", "buyer_country": "SA"},
     [("Integration project, milestone 2", "1", "18500.00", "0")], "waiting"),
    (0, "standard", {"buyer_name": "Red Sea Hotels (demo)", "buyer_registration_scheme": "CRN", "buyer_registration_id": "4030000000", "buyer_street": "Corniche Road", "buyer_city": "Jeddah", "buyer_postal_code": "23511", "buyer_country": "SA"},
     [("Guest Wi-Fi assistant, annual", "1", "9600.00", "600.00")], "draft"),
]
EG_INVOICES = [
    (8, "b2b", {"buyer_name": "Delta Trading (demo)", "buyer_tax_number": "200300400", "buyer_street": "El Horreya Road", "buyer_building_number": "52", "buyer_city": "Alexandria", "buyer_region": "Alexandria", "buyer_country": "EG"},
     [("Mobile app maintenance", "1", "45000.00", "0"), ("Cloud hosting, October", "1", "8250.00", "250.00")], "accepted"),
    (2, "b2b", {"buyer_name": "Cairo Clinics Group (demo)", "buyer_tax_number": "300400500", "buyer_street": "Abbas El Akkad", "buyer_building_number": "9", "buyer_city": "Nasr City", "buyer_region": "Cairo", "buyer_country": "EG"},
     [("Booking assistant licences", "25", "380.00", "0")], "submitted"),
    (1, "b2c", {"buyer_name": "Mona Saleh"}, [("Online course seat", "1", "2400.00", "0")], "error"),
]


def _lines(country, rows):
    out = []
    for i, row in enumerate(rows, start=1):
        description, quantity, price, discount = row[:4]
        line = {"description": description, "quantity": quantity, "unit_price": price, "discount": discount}
        if country == "SA":
            line.update({"vat_category": row[4] if len(row) > 4 else "S", "vat_rate": row[5] if len(row) > 5 else "15"})
            if len(row) > 6:
                line.update({"exemption_code": row[6], "exemption_reason": row[7]})
            line["unit_code"] = "PCE"
        else:
            line.update({"vat_category": "V009", "vat_rate": "14", "item_type": "EGS", "item_code": f"EG-{EG_TAX}-{1000 + i}", "unit_code": "EA"})
        out.append(line)
    return out


def _sa_answer(invoice, state):
    mode = "clearance" if invoice.invoice_type == "standard" else "reporting"
    key = "clearanceStatus" if mode == "clearance" else "reportingStatus"
    if state == "accepted":
        return {key: "CLEARED" if mode == "clearance" else "REPORTED"}, {
            "mode": mode, "http_status": 200, "warnings": False, "status": "PASS", "errorMessages": [], "warningMessages": [],
            "infoMessages": [{"type": "INFO", "code": "XSD_ZATCA_VALID", "category": "XSD validation", "message": "Complied with UBL 2.1 standards (simulated in the demo)", "status": "PASS"}],
        }
    return {key: "NOT_REPORTED"}, {
        "mode": mode, "http_status": 400, "warnings": False, "status": "ERROR", "warningMessages": [], "infoMessages": [],
        "errorMessages": [{"type": "ERROR", "code": "DEMO-REJECTED", "category": "Demo", "message": "Example rejection: the totals did not match (simulated answer in the demo)", "status": "ERROR"}],
    }


def seed(org, users, now):
    from actions.models import ActionProposal
    from einvoice import services
    from einvoice.models import AuthorityEvent, Invoice

    admin, member = users["admin"], users["member"]
    sa = _sa_profile(org, admin, now)
    _eg_profile(org, admin, now)
    can_sign = sa.onboarding == sa.ONB_PRODUCTION

    for days, kind, buyer, rows, state in SA_INVOICES:
        at = now - timedelta(days=days, hours=3)
        data = {"country": "SA", "invoice_type": kind, "issue_datetime": at.isoformat(), "lines": _lines("SA", rows), **buyer}
        invoice = services.save_invoice(admin, org, data, source="demo")
        Invoice.objects.filter(pk=invoice.pk).update(created_at=at)
        if state == "draft" or not can_sign:
            continue
        invoice = services.prepare(admin, org, invoice.id)
        if state == "waiting":
            proposal = ActionProposal.objects.create(
                org=org, user=admin, tool_key="einvoice.submit", arguments={"invoice": str(invoice.id)},
                summary=f"Send {invoice.number} (SAR {Decimal(invoice.tax_inclusive):,.2f}) to ZATCA for clearance [demo, simulated]",
                created_at=now - timedelta(hours=2), expires_at=now + timedelta(hours=22),
            )
            invoice.proposal = proposal
            invoice.save(update_fields=["proposal"])
            continue
        raw, response = _sa_answer(invoice, state)
        invoice.status = Invoice.ACCEPTED if state == "accepted" else Invoice.REJECTED
        invoice.authority_status = next(iter(raw.values()))
        invoice.authority_response = response
        invoice.simulated = True
        invoice.submitted_at = at + timedelta(minutes=12)
        invoice.decided_at = at + timedelta(minutes=12)
        if invoice.invoice_type == "standard" and state == "accepted":
            invoice.cleared_xml = invoice.xml
        invoice.save()
        AuthorityEvent.objects.create(org=org, invoice=invoice, country="SA", action=response["mode"], http_status=response["http_status"], outcome="accepted" if state == "accepted" else "rejected", response=response, simulated=True, actor=admin, created_at=at + timedelta(minutes=12))

    for days, kind, buyer, rows, state in EG_INVOICES:
        at = now - timedelta(days=days, hours=5)
        data = {"country": "EG", "invoice_type": kind, "issue_datetime": at.isoformat(), "lines": _lines("EG", rows), **buyer}
        invoice = services.save_invoice(member if state == "error" else admin, org, data, source="demo")
        Invoice.objects.filter(pk=invoice.pk).update(created_at=at)
        invoice = services.prepare(admin, org, invoice.id)
        invoice.simulated = True
        invoice.submitted_at = at + timedelta(minutes=20)
        if state == "error":
            invoice.status, invoice.authority_status = Invoice.ERROR, "signer_failed"
            invoice.authority_response = {"error": "The signer service did not answer. Check that the USB token is plugged in. (demo)"}
            action, outcome, http = "sign", "error", None
        else:
            invoice.eta_signature, invoice.eta_signature_simulated = "DEMO-SIMULATED-SIGNATURE", True
            n = f"DEMO{invoice.number.replace('-', '')}".ljust(26, "0")[:26]
            invoice.authority_uuid, invoice.authority_submission, invoice.authority_long_id = n, f"DEMOSUB{n[7:]}"[:26], f"{n}LONGID".ljust(42, "0")[:42]
            invoice.status = Invoice.ACCEPTED if state == "accepted" else Invoice.SUBMITTED
            invoice.authority_status = "valid" if state == "accepted" else "submitted"
            invoice.authority_response = {"http_status": 202, "submission": invoice.authority_submission, "uuid": n, "long_id": invoice.authority_long_id, "rejected": [], "error": None}
            if state == "accepted":
                invoice.decided_at = at + timedelta(minutes=35)
                invoice.authority_response["overall_status"] = "valid"
            action, outcome, http = "submit", "submitted", 202
        invoice.save()
        AuthorityEvent.objects.create(org=org, invoice=invoice, country="EG", action=action, http_status=http, outcome=outcome, response=invoice.authority_response, simulated=True, actor=admin, created_at=at + timedelta(minutes=20))

    from buddies.models import Buddy

    back_office = Buddy.objects.filter(org=org, slug="back-office").first()
    if back_office is not None:
        back_office.allowed_tools = list(dict.fromkeys([*(back_office.allowed_tools or []), "einvoice.prepare"]))
        presets = list(back_office.preset_prompts or [])
        presets.append({"label": "ZATCA invoice", "prompt": "Draft a ZATCA e-invoice for Gulf Retail for 4,500 SAR"})
        back_office.preset_prompts = presets
        back_office.save(update_fields=["allowed_tools", "preset_prompts"])

    org.refresh_from_db(fields=["settings"])
    settings_value = dict(org.settings or {})
    settings_value["data_region"] = {"region": "sa", "pinned": False}
    org.settings = settings_value
    org.save(update_fields=["settings"])
