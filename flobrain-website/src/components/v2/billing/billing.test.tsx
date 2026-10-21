import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { translate } from "@/i18n/phrases";

import { describeChanges, toPricePlan, type ServerPlan, type SwitchPreview } from "./billing";
import { InvoiceList } from "./InvoiceList";
import { PlanSwitch } from "./PlanSwitch";
import { calculate } from "./pricing";
import { WorkspaceAiMeter } from "./WorkspaceAiMeter";

const post = vi.fn();
vi.mock("@/lib/v2/api", async (orig) => ({ ...(await orig<typeof import("@/lib/v2/api")>()), api: { post: (...args: unknown[]) => post(...args) } }));

const tr = (text: string, vars?: Record<string, string | number>) => translate("en", text, vars);

const base = { id: "x", currency: "USD", interval: "month", entitlements: { flags: [] }, sample: true };
const FLEET: ServerPlan = { ...base, code: "fleet", name: "Fleet (Sample)", price_cents: 1200, billing_unit: "per_seat", price_monthly_cents: 1200, price_yearly_cents: 12000, tier: "fleet" };
const STUDIO: ServerPlan = {
  ...base,
  code: "studio",
  name: "Studio (Sample)",
  price_cents: 19900,
  billing_unit: "per_workspace",
  included_seats: 25,
  ai_allowance_per_workspace: 30000,
  overage_policy: "prompt_upgrade",
  price_monthly_cents: 19900,
  price_yearly_cents: 198000,
  tier: "fleet",
};

const PREVIEW: SwitchPreview = {
  preview: true,
  sample: true,
  proration: "stripe",
  from: { plan: "fleet", name: "Fleet (Sample)", billing_unit: "per_seat", interval: "month", seats: 8, seat_cap: null, per_month_cents: 9600, per_year_cents: 115200, charge_cents: 9600, currency: "USD", ai: { basis: "per_seat", per_seat: 1500, total: 12000 }, overage_policy: "block" },
  to: { plan: "studio", name: "Studio (Sample)", billing_unit: "per_workspace", interval: "year", seats: 25, seat_cap: 25, per_month_cents: 16500, per_year_cents: 198000, charge_cents: 198000, currency: "USD", ai: { basis: "per_workspace", per_seat: null, total: 30000 }, overage_policy: "prompt_upgrade" },
  changes: [
    { key: "plan", from: "Fleet (Sample)", to: "Studio (Sample)" },
    { key: "billing_unit", from: "per_seat", to: "per_workspace" },
    { key: "interval", from: "month", to: "year" },
    { key: "seats", from: 8, to: 25 },
    { key: "charge_cents", from: 9600, to: 198000 },
    { key: "ai", from: {}, to: {} },
    { key: "seat_cap", from: null, to: 25 },
  ],
};

describe("billing helpers", () => {
  it("maps server plan rows into the same math as the site", () => {
    const calc = calculate([FLEET, STUDIO].map(toPricePlan), 17, "month");
    expect(calc.cheaper).toBe("studio");
    expect(calc.plans.map((r) => r.perMonthCents)).toEqual([20400, 19900]);
    expect(toPricePlan({ ...base, code: "old", name: "Old", price_cents: 5000, interval: "year" })).toMatchObject({ monthCents: null, yearCents: 5000, billingUnit: "per_seat" });
  });

  it("states exactly what changes", () => {
    const lines = describeChanges(PREVIEW, tr, "en-US");
    expect(lines).toEqual([
      "Plan: Fleet (Sample) becomes Studio (Sample).",
      "Billing: per person becomes per workspace.",
      "Billed: monthly becomes yearly.",
      "Seats: 8 seats becomes up to 25 people.",
      "Price: $96 a month becomes $1,980 a year.",
      "AI included: 1,500 buddy answers per person (12,000 a month) becomes 30,000 buddy answers a month for the whole workspace.",
      "People: up to 25. New invites stop there, and we never charge for extra people.",
    ]);
    const first = describeChanges({ ...PREVIEW, from: null, changes: [] }, tr, "en-US");
    expect(first[0]).toBe("You start on Studio (Sample), per workspace, billed yearly.");
  });

  it("formats amounts in Arabic", () => {
    const arabic = (text: string, vars?: Record<string, string | number>) => translate("ar", text, vars);
    const lines = describeChanges(PREVIEW, arabic, "ar-EG");
    expect(lines.join(" ")).toMatch(/[٠-٩]/);
    render(<InvoiceList locale="ar-EG" invoices={[{ id: "1", number: "DEMO-202610", status: "paid", amount_cents: 19900, currency: "USD", plan: "studio", period_start: "2026-10-01T00:00:00Z", period_end: null, created_at: "2026-10-01T09:00:00Z", url: "", demo: true }]} />);
    expect(screen.getByText("DEMO-202610")).toBeInTheDocument();
    expect(screen.getByRole("table").textContent).toMatch(/١٩٩/);
  });
});

describe("billing components", () => {
  beforeEach(() => post.mockReset());

  it("shows the workspace AI pool", () => {
    render(<WorkspaceAiMeter ai={{ basis: "per_workspace", per_seat: null, total: 30000, used: 7500 }} sample locale="en-US" />);
    expect(screen.getByText("30,000 buddy answers a month for the whole workspace, shared by everyone.")).toBeInTheDocument();
    expect(screen.getByRole("meter")).toHaveAttribute("aria-valuenow", "25");
    expect(screen.getByText("Sample numbers")).toBeInTheDocument();
  });

  it("marks the cheaper plan, previews, confirms and reports the result", async () => {
    const done = vi.fn();
    post.mockResolvedValueOnce(PREVIEW).mockResolvedValueOnce({ ...PREVIEW, mode: "demo", status: "applied" });
    render(<PlanSwitch orgId="o1" plans={[FLEET, STUDIO]} currentCode="fleet" currentInterval="month" seatsUsed={18} checkout="demo" canManage locale="en-US" onDone={done} />);
    expect(screen.getByText(/^For 18 people, Studio \(Sample\) is cheaper by \$204 a year\. Studio \(Sample\) costs less from 17 people\.$/)).toBeInTheDocument();
    expect(screen.getAllByText("Cheaper for your team")).toHaveLength(1);
    fireEvent.click(screen.getByRole("radio", { name: "Yearly" }));
    fireEvent.click(screen.getByRole("button", { name: "Switch to Studio (Sample)" }));
    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
    expect(post).toHaveBeenCalledWith("/orgs/o1/billing/switch", { plan: "studio", interval: "year", seats: undefined });
    expect(screen.getByText("Price: $96 a month becomes $1,980 a year.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Confirm switch" }));
    await waitFor(() => expect(done).toHaveBeenCalledWith("Demo: your plan changed. No payment was taken."));
    expect(post.mock.calls[1][1]).toMatchObject({ plan: "studio", interval: "year", confirm: true });
  });

  it("does not offer a plan the team does not fit, and hides switching for non-owners", () => {
    const { rerender } = render(<PlanSwitch orgId="o1" plans={[FLEET, STUDIO]} currentCode="fleet" currentInterval="month" seatsUsed={30} checkout="stripe" canManage locale="en-US" onDone={vi.fn()} />);
    expect(screen.getByText("Fits up to 25 people.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Switch to Studio (Sample)" })).toBeNull();
    rerender(<PlanSwitch orgId="o1" plans={[FLEET, STUDIO]} currentCode="studio" currentInterval="month" seatsUsed={3} checkout="stripe" canManage={false} locale="en-US" onDone={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /Switch to/ })).toBeNull();
    expect(screen.getByText("Only the owner can change the plan.")).toBeInTheDocument();
  });
});
