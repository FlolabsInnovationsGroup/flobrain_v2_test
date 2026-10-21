"""Server-side totals and rounding for both countries. Decimal only, never float.

Saudi Arabia (ZATCA XML Implementation Standard, EN 16931 rules it adopts):
- amounts have 2 decimals, rounded half up; only final results are rounded (BR-DEC-*);
- line net amount (BT-131) = quantity x unit price - line allowance, rounded to 2 decimals;
- line VAT (KSA-11) = line net x rate / 100, rounded; line amount with VAT (KSA-12) = net + VAT;
- VAT per category (BR-CO-17, BR-S-09): taxable amount (sum of line nets in that category and
  rate) x rate / 100, rounded once at document level. The document VAT (BT-110) is the sum of the
  category amounts, not of the rounded line amounts, so it can differ from them by a few halalas.
- BT-106 = sum of line nets; BT-109 = BT-106 (no document-level allowances or charges here);
  BT-112 = BT-109 + BT-110; BT-115 payable = BT-112 (no prepayment).

Egypt (ETA SDK, invoice v1.0): amounts up to 5 decimals.
- salesTotal = quantity x unit value in EGP; netTotal = salesTotal - discount amount;
- T1 (VAT) amount = netTotal x rate / 100; line total = netTotal + T1;
- totalSalesAmount, totalDiscountAmount, netAmount = sales - discount, taxTotals (T1 = sum of the
  line amounts), totalAmount = netAmount + taxes. Other ETA tax types (T2..T20), value
  difference, taxable fees and items discounts are not modelled and are sent as 0.
  The SDK page does not spell out the rounding of a line tax: we round each amount to 5
  decimals half up, which the ETA accepts within its precision rules (unverified for edge cases).
"""

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

TWO = Decimal("0.01")
FIVE = Decimal("0.00001")
SIX = Decimal("0.000001")
HUNDRED = Decimal("100")
MAX_AMOUNT = Decimal("999999999999")

SA_CATEGORIES = {"S", "Z", "E", "O"}
EG_SUBTYPES = {f"V{n:03d}" for n in range(1, 11)}


class MoneyError(ValueError):
    pass


def dec(value, name: str, *, minimum: Decimal | None = Decimal("0"), places: int = 5) -> Decimal:
    """A finite Decimal from a string or int (floats go through ``str`` so 0.1 stays 0.1)."""
    if isinstance(value, bool) or value is None or value == "":
        raise MoneyError(f"{name} is required")
    if isinstance(value, float):
        value = repr(value)
    try:
        out = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise MoneyError(f"{name} must be a number") from exc
    if not out.is_finite():
        raise MoneyError(f"{name} must be a number")
    if minimum is not None and out < minimum:
        raise MoneyError(f"{name} can't be below {minimum}")
    if abs(out) > MAX_AMOUNT:
        raise MoneyError(f"{name} is too large")
    exponent = out.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -places:
        raise MoneyError(f"{name} has more than {places} decimals")
    return out


def q2(value: Decimal) -> Decimal:
    return value.quantize(TWO, rounding=ROUND_HALF_UP)


def q5(value: Decimal) -> Decimal:
    return value.quantize(FIVE, rounding=ROUND_HALF_UP)


def fmt2(value) -> str:
    return f"{q2(Decimal(value)):.2f}"


def fmt_eta(value) -> str:
    """Up to 5 decimals, at least 2, no exponent: 1000 -> "1000.00", 0.142857 -> "0.14286"."""
    text = f"{q5(Decimal(value)):.5f}"
    whole, frac = text.split(".")
    frac = frac.rstrip("0")
    return f"{whole}.{frac.ljust(2, '0')}"


@dataclass
class LineIn:
    description: str
    quantity: Decimal
    unit_price: Decimal
    discount: Decimal = Decimal("0")
    vat_category: str = "S"
    vat_rate: Decimal = Decimal("15")
    exemption_code: str = ""
    exemption_reason: str = ""


@dataclass
class LineOut:
    gross: Decimal
    net: Decimal
    vat: Decimal
    total: Decimal


@dataclass
class Totals:
    lines: list = field(default_factory=list)
    line_extension: Decimal = Decimal("0")
    discount_total: Decimal = Decimal("0")
    tax_exclusive: Decimal = Decimal("0")
    tax_total: Decimal = Decimal("0")
    tax_inclusive: Decimal = Decimal("0")
    payable: Decimal = Decimal("0")
    breakdown: list = field(default_factory=list)  # [{category, rate, taxable, tax, exemption_code, exemption_reason}]


def _check_sa_line(line: LineIn, i: int) -> None:
    if line.vat_category not in SA_CATEGORIES:
        raise MoneyError(f"line {i}: VAT category must be S, Z, E or O")
    if line.vat_category == "S" and line.vat_rate <= 0:
        raise MoneyError(f"line {i}: standard rated lines need a rate above 0")
    if line.vat_category != "S" and line.vat_rate != 0:
        raise MoneyError(f"line {i}: zero rated, exempt and out of scope lines have a 0% rate")
    if line.vat_category != "S" and not line.exemption_code:
        raise MoneyError(f"line {i}: give the exemption reason code (VATEX-SA-…)")
    if line.vat_category == "S" and line.exemption_code:
        raise MoneyError(f"line {i}: standard rated lines have no exemption reason (BR-S-10)")


def sa_totals(lines: list[LineIn]) -> Totals:
    if not lines:
        raise MoneyError("add at least one line")
    out = Totals()
    groups: dict[tuple, dict] = {}
    for i, line in enumerate(lines, start=1):
        _check_sa_line(line, i)
        if line.quantity <= 0:
            raise MoneyError(f"line {i}: quantity must be above 0")
        gross = line.quantity * line.unit_price
        if line.discount > gross:
            raise MoneyError(f"line {i}: the discount is larger than the line amount")
        net = q2(gross - line.discount)
        vat = q2(net * line.vat_rate / HUNDRED)
        out.lines.append(LineOut(gross=q2(gross), net=net, vat=vat, total=net + vat))
        out.line_extension += net
        out.discount_total += line.discount
        key = (line.vat_category, line.vat_rate, line.exemption_code)
        group = groups.setdefault(key, {"category": line.vat_category, "rate": line.vat_rate, "taxable": Decimal("0"), "exemption_code": line.exemption_code, "exemption_reason": line.exemption_reason})
        group["taxable"] += net
    for group in groups.values():
        group["tax"] = q2(group["taxable"] * group["rate"] / HUNDRED)
        out.tax_total += group["tax"]
        out.breakdown.append(group)
    out.discount_total = q2(out.discount_total)
    out.tax_exclusive = out.line_extension
    out.tax_inclusive = out.tax_exclusive + out.tax_total
    out.payable = out.tax_inclusive
    return out


def eg_totals(lines: list[LineIn], exchange_rate: Decimal | None = None) -> Totals:
    """``unit_price`` is in the invoice currency; with ``exchange_rate`` (EGP per unit) it is
    converted to EGP per unit and rounded to 5 decimals (the ETA ``amountEGP`` rule)."""
    if not lines:
        raise MoneyError("add at least one line")
    out = Totals()
    t1 = Decimal("0")
    for i, line in enumerate(lines, start=1):
        if line.quantity <= 0:
            raise MoneyError(f"line {i}: quantity must be above 0")
        if line.vat_category not in EG_SUBTYPES:
            raise MoneyError(f"line {i}: VAT subtype must be V001 to V010")
        if line.vat_rate < 0 or line.vat_rate > 999:
            raise MoneyError(f"line {i}: rate must be between 0 and 999")
        unit_egp = q5(line.unit_price * exchange_rate) if exchange_rate else line.unit_price
        sales = q5(line.quantity * unit_egp)
        discount = q5(line.discount * exchange_rate) if exchange_rate else q5(line.discount)
        if discount > sales:
            raise MoneyError(f"line {i}: the discount is larger than the line amount")
        net = sales - discount
        vat = q5(net * line.vat_rate / HUNDRED)
        out.lines.append(LineOut(gross=sales, net=net, vat=vat, total=net + vat))
        out.line_extension += sales
        out.discount_total += discount
        t1 += vat
    out.tax_exclusive = out.line_extension - out.discount_total  # netAmount
    out.tax_total = t1
    out.tax_inclusive = out.tax_exclusive + t1  # totalAmount
    out.payable = out.tax_inclusive
    out.breakdown = [{"category": "T1", "rate": None, "taxable": out.tax_exclusive, "tax": t1, "exemption_code": "", "exemption_reason": ""}]
    return out
