"""Totals and rounding for Saudi and Egyptian invoices (no database)."""

from decimal import Decimal as D

from django.test import SimpleTestCase

from einvoice import money
from einvoice.money import LineIn


def sa(*lines):
    return money.sa_totals([LineIn(*line) for line in lines])


class SaudiTotalsTests(SimpleTestCase):
    def test_single_line(self):
        t = sa(("Widget", D("3"), D("33.33"), D("1"), "S", D("15")))
        line = t.lines[0]
        self.assertEqual(line.net, D("98.99"))
        self.assertEqual(line.vat, D("14.85"))  # 14.8485 rounds half up
        self.assertEqual(line.total, D("113.84"))
        self.assertEqual((t.line_extension, t.tax_total, t.tax_inclusive, t.payable), (D("98.99"), D("14.85"), D("113.84"), D("113.84")))

    def test_half_up_not_bankers(self):
        # 0.10 x 15% = 0.015 -> 0.02 (half up), banker's rounding would give 0.02 too; 0.70 x 15% = 0.105 -> 0.11
        t = sa(("A", D("1"), D("0.70"), D("0"), "S", D("15")))
        self.assertEqual(t.tax_total, D("0.11"))

    def test_category_vat_is_rounded_once_not_summed_from_lines(self):
        # Three lines of 0.10 at 15%: each line VAT 0.015 -> 0.02 (sum 0.06), category VAT 0.30 x 15% = 0.045 -> 0.05
        t = sa(*[("A", D("1"), D("0.10"), D("0"), "S", D("15"))] * 3)
        self.assertEqual(sum(l.vat for l in t.lines), D("0.06"))
        self.assertEqual(t.tax_total, D("0.05"))
        self.assertEqual(t.tax_inclusive, D("0.35"))

    def test_mixed_categories_breakdown(self):
        t = sa(("A", D("2"), D("100"), D("0"), "S", D("15")), ("Book", D("1"), D("50"), D("0"), "Z", D("0"), "VATEX-SA-EDU", "Education"))
        groups = {g["category"]: g for g in t.breakdown}
        self.assertEqual(groups["S"]["taxable"], D("200"))
        self.assertEqual(groups["S"]["tax"], D("30.00"))
        self.assertEqual(groups["Z"]["tax"], D("0.00"))
        self.assertEqual(t.tax_inclusive, D("280.00"))

    def test_rules(self):
        with self.assertRaises(money.MoneyError):
            sa(("A", D("1"), D("10"), D("0"), "Z", D("0")))  # zero rated needs an exemption code
        with self.assertRaises(money.MoneyError):
            sa(("A", D("1"), D("10"), D("0"), "S", D("15"), "VATEX-SA-EDU"))  # BR-S-10
        with self.assertRaises(money.MoneyError):
            sa(("A", D("1"), D("10"), D("0"), "E", D("5"), "VATEX-SA-29"))  # exempt at 5%
        with self.assertRaises(money.MoneyError):
            sa(("A", D("1"), D("10"), D("11"), "S", D("15")))  # discount above the line
        with self.assertRaises(money.MoneyError):
            sa(("A", D("0"), D("10"), D("0"), "S", D("15")))
        with self.assertRaises(money.MoneyError):
            money.sa_totals([])

    def test_parsing(self):
        self.assertEqual(money.dec("1.10", "x"), D("1.10"))
        self.assertEqual(money.dec(0.1, "x"), D("0.1"))  # floats go through repr, not binary
        for bad in ("abc", "NaN", "Infinity", "-1", "", None, True, "1.123456"):
            with self.assertRaises(money.MoneyError, msg=bad):
                money.dec(bad, "x")
        self.assertEqual(money.fmt2(D("2.005")), "2.01")


class EgyptTotalsTests(SimpleTestCase):
    def test_line_and_totals(self):
        t = money.eg_totals([LineIn("App", D("3"), D("333.33333"), D("10"), "V009", D("14"))])
        line = t.lines[0]
        self.assertEqual(line.gross, D("999.99999"))
        self.assertEqual(line.net, D("989.99999"))
        self.assertEqual(line.vat, D("138.60000"))  # 138.5999986 -> 5 decimals half up
        self.assertEqual(t.tax_exclusive, D("989.99999"))  # netAmount = sales - discount
        self.assertEqual(t.tax_inclusive, D("1128.59999"))  # totalAmount = net + T1

    def test_foreign_currency(self):
        t = money.eg_totals([LineIn("Licence", D("2"), D("100"), D("0"), "V009", D("14"))], exchange_rate=D("48.12345"))
        self.assertEqual(t.lines[0].gross, D("9624.69000"))
        self.assertEqual(t.tax_total, D("1347.45660"))

    def test_rules(self):
        with self.assertRaises(money.MoneyError):
            money.eg_totals([LineIn("A", D("1"), D("10"), D("0"), "S", D("14"))])  # not a T1 subtype
        with self.assertRaises(money.MoneyError):
            money.eg_totals([LineIn("A", D("1"), D("10"), D("20"), "V009", D("14"))])

    def test_eta_number_format(self):
        self.assertEqual(money.fmt_eta(D("1000")), "1000.00")
        self.assertEqual(money.fmt_eta(D("0.142857")), "0.14286")
        self.assertEqual(money.fmt_eta(D("14")), "14.00")
        self.assertEqual(money.fmt_eta(D("272.07000")), "272.07")
