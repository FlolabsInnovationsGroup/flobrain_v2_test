"""Demo model answers for e-invoicing (``DEMO_AI`` only).

When a buddy that is offered ``einvoice.prepare`` is asked for a Saudi or Egyptian e-invoice
("draft a ZATCA invoice for Gulf Retail for 4,500 SAR", "فاتورة إلكترونية لمصر بمبلغ ٢٠٠٠"),
the demo model proposes the tool with a draft. Nothing is created until a person approves it,
and approving only creates a draft: signing and sending stay separate, approved steps.
Everything else passes on (returns None).
"""

import json
import re

from brain.llm.demo_ai import _question, _result

BUDDY_MARK = "You are a FloBrain buddy"
TOOL = "einvoice__prepare"
LABEL = "(Prepared by FloBrain's demo model.)"
I = re.IGNORECASE
WANTS = re.compile(r"e-?invoice|zatca|fatoora|\beta\b|فاتورة|tax invoice", I)
SAUDI = re.compile(r"zatca|fatoora|saudi|\bsar\b|riyal|ksa|السعودي|ريال", I)
EGYPT = re.compile(r"\beta\b|egypt|\begp\b|pound|مصر|جنيه", I)
ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩٬", "0123456789,")
AMOUNT = re.compile(r"(\d[\d,]*(?:\.\d{1,2})?)\s*(k)?\b", I)


def _names(tools):
    return {t.get("function", {}).get("name", "") for t in tools or []}


def _amount(text: str) -> str:
    for match in AMOUNT.finditer(text.translate(ARABIC_DIGITS)):
        value = float(match.group(1).replace(",", "")) * (1000 if match.group(2) else 1)
        if value > 0:
            return f"{value:.2f}"
    return "1000.00"


def _buyer(text: str) -> str:
    match = re.search(r"\bfor\s+([A-Z][\w&.\- ]{1,60}?)(?:\s+(?:for|of|worth|at|in)\b|[,.]|$)", text)
    return match.group(1).strip() if match else ""


def handle(system, user, messages, tools):
    if not tools or BUDDY_MARK not in (system or "") or TOOL not in _names(tools):
        return None
    question = (_question(messages) or user or "").strip()
    if not WANTS.search(question):
        return None
    country = "EG" if EGYPT.search(question) and not SAUDI.search(question) else "SA"
    buyer = _buyer(question)
    if country == "SA":
        kind = "standard" if buyer or re.search(r"\b(b2b|standard|company)\b", question, I) else "simplified"
        line = {"description": "Services as agreed", "quantity": "1", "unit_price": _amount(question), "vat_category": "S", "vat_rate": "15"}
    else:
        kind = "b2b" if buyer or re.search(r"\b(b2b|company)\b", question, I) else "b2c"
        line = {"description": "Services as agreed", "quantity": "1", "unit_price": _amount(question), "vat_category": "V009", "vat_rate": "14", "item_type": "EGS", "item_code": "EG-100200300-1001"}
    args = {"country": country, "invoice_type": kind, "lines": [line], "note": f"Drafted in a buddy chat {LABEL}"}
    if buyer:
        args["buyer_name"] = buyer
    text = (
        "I prepared a draft e-invoice for your approval. Approving creates a draft only: you review it, "
        f"then prepare and send it to {'ZATCA' if country == 'SA' else 'the ETA'} as separate steps. {LABEL}"
    )
    return _result(text, [{"name": TOOL, "arguments": json.dumps(args)}])
