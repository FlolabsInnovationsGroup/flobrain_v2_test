/**
 * Live totals for the invoice form. The server recomputes everything (einvoice/money.py) and its
 * numbers are the ones that count; this mirrors the same rules so the form shows the same result.
 * Exact decimal arithmetic with scaled BigInts (no floating point), rounding half up.
 *
 * Saudi Arabia: 2 decimals; line net = qty x price - discount; line VAT = net x rate; the document
 * VAT is computed per category (sum of nets x rate, rounded once), not summed from lines.
 * Egypt: 5 decimals; salesTotal = qty x price (x exchange rate); net = sales - discount;
 * T1 = net x rate; total = net + T1.
 */

import type { Country, Line } from "./types";

// BigInt() calls instead of literals: the project targets ES2017.
const ZERO = BigInt(0);
const TWO = BigInt(2);
const HUNDRED = BigInt(100);
const SCALE = 12; // internal precision: 12 decimals

function pow10(n: number): bigint {
  let out = BigInt(1);
  for (let i = 0; i < n; i += 1) out *= BigInt(10);
  return out;
}

const ONE = pow10(SCALE);

export function parse(value: string | number | undefined | null): bigint | null {
  const text = String(value ?? "").trim();
  if (!/^-?\d+(\.\d+)?$/.test(text)) return null;
  const negative = text.startsWith("-");
  const [whole, frac = ""] = text.replace("-", "").split(".");
  if (frac.length > SCALE) return null;
  const n = BigInt(whole) * ONE + BigInt(frac.padEnd(SCALE, "0") || "0");
  return negative ? -n : n;
}

function mul(a: bigint, b: bigint): bigint {
  return (a * b) / ONE; // exact while the product fits the 12-decimal scale; inputs have at most 6
}

/** Round half up (away from zero for ties) to ``places`` decimals. */
export function round(value: bigint, places: number): bigint {
  const unit = pow10(SCALE - places);
  const negative = value < ZERO;
  const abs = negative ? -value : value;
  const q = (abs + unit / TWO) / unit;
  return (negative ? -q : q) * unit;
}

export function format(value: bigint, places: number): string {
  const r = round(value, places);
  const negative = r < ZERO;
  const abs = negative ? -r : r;
  const whole = abs / ONE;
  const frac = (abs % ONE).toString().padStart(SCALE, "0").slice(0, places);
  return `${negative ? "-" : ""}${whole}${places ? `.${frac}` : ""}`;
}

export type LineTotals = { net: bigint; vat: bigint; total: bigint } | null;
export type Totals = { lines: LineTotals[]; net: bigint; vat: bigint; total: bigint; valid: boolean };

export function totals(country: Country, lines: Line[], exchangeRate?: string | null): Totals {
  const places = country === "SA" ? 2 : 5;
  const rate = country === "EG" && exchangeRate ? parse(exchangeRate) : null;
  const groups = new Map<string, { net: bigint; rate: bigint }>();
  let net = ZERO;
  let lineVat = ZERO;
  let valid = lines.length > 0;
  const out: LineTotals[] = lines.map((line) => {
    const qty = parse(line.quantity || "1");
    let price = parse(line.unit_price);
    let discount = parse(line.discount || "0");
    const vatRate = parse(line.vat_rate);
    if (qty === null || price === null || discount === null || vatRate === null || qty <= ZERO || price < ZERO || discount < ZERO) {
      valid = false;
      return null;
    }
    if (rate !== null) {
      price = round(mul(price, rate), 5);
      discount = round(mul(discount, rate), 5);
    } else if (country === "EG") {
      discount = round(discount, 5);
    }
    const gross = country === "SA" ? mul(qty, price) : round(mul(qty, price), 5);
    if (discount > gross) {
      valid = false;
      return null;
    }
    const lineNet = country === "SA" ? round(gross - discount, 2) : gross - discount;
    const vat = round(mul(lineNet, vatRate) / HUNDRED, places);
    net += lineNet;
    lineVat += vat;
    const key = `${line.vat_category}|${vatRate}|${line.exemption_code ?? ""}`;
    const group = groups.get(key) ?? { net: ZERO, rate: vatRate };
    group.net += lineNet;
    groups.set(key, group);
    return { net: lineNet, vat, total: lineNet + vat };
  });
  let vat = lineVat;
  if (country === "SA") {
    vat = ZERO;
    for (const group of groups.values()) vat += round(mul(group.net, group.rate) / HUNDRED, 2);
  }
  return { lines: out, net, vat, total: net + vat, valid };
}

/**
 * An amount for people to read: at least 2 decimals, trailing zeros after that removed, so an
 * Egyptian 5-decimal total "2736.00000" reads "2736.00" while "12.34567" keeps its precision.
 * String-based: the server's exact value is never rounded here.
 */
export function display(value: string | number | undefined | null): string {
  const text = String(value ?? "").trim();
  const match = /^(-?\d+)(?:\.(\d+))?$/.exec(text);
  if (!match) return text;
  const decimals = (match[2] ?? "").replace(/0+$/, "").padEnd(2, "0");
  return `${match[1]}.${decimals}`;
}
