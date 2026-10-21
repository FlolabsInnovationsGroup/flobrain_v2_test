"use client";

import { Check } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { CALCULATOR_PLANS, PRICE_BOOK, calculate, formatMoney, yearlySavingPct, type Interval } from "@/components/v2/billing/pricing";
import { Segmented } from "@/components/v2/billing/Segmented";

import { PLAN_VIEWS, type PriceView } from "./content";

const usd = (cents: number) => formatMoney(cents, "en-US");
const SLIDER_MAX = 40;

export function Plans() {
  const [yearly, setYearly] = useState(true);
  const [view, setView] = useState<PriceView>("per_seat");
  const plans = PLAN_VIEWS[view];
  const saving = yearlySavingPct(PRICE_BOOK.fleet);
  return (
    <div style={{ marginTop: 40, display: "flex", flexDirection: "column", alignItems: "center" }}>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 12, justifyContent: "center" }}>
        <Segmented
          label="How you pay"
          className="tabbar"
          value={view}
          onChange={setView}
          options={[
            { value: "per_seat", label: "Per person" },
            { value: "per_workspace", label: "Per workspace" },
          ]}
        />
        <Segmented
          label="Billing"
          className="tabbar"
          value={yearly ? "year" : "month"}
          onChange={(v) => setYearly(v === "year")}
          options={[
            { value: "month", label: "Monthly" },
            {
              value: "year",
              label: (
                <>
                  Yearly
                  {saving ? (
                    <span className="mono" style={{ fontSize: 10.5, color: "var(--gr)" }}>
                      SAVE {saving}%
                    </span>
                  ) : null}
                </>
              ),
            },
          ]}
        />
      </div>
      <div className="plans" style={{ marginTop: 36, width: "100%", textAlign: "left" }}>
        {plans.map((plan) => {
          const price = yearly ? plan.yearly : plan.monthly;
          const custom = price === "Custom";
          return (
            <section
              key={plan.name}
              aria-labelledby={`plan-${plan.name}`}
              className="card"
              style={{
                padding: 30,
                display: "flex",
                flexDirection: "column",
                ...(plan.featured
                  ? {
                      boxShadow: "inset 0 0 0 1px rgba(124,107,255,.55), 0 40px 80px -40px rgba(124,107,255,.6)",
                      background: "radial-gradient(90% 50% at 50% 0%,rgba(124,107,255,.22),transparent 70%),linear-gradient(180deg,var(--s2),var(--s1))",
                    }
                  : {}),
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <h2 id={`plan-${plan.name}`} style={{ margin: 0, font: "600 22px var(--fd)" }}>
                  {plan.name}
                </h2>
                {plan.featured ? (
                  <span className="mono tag" style={{ background: "rgba(124,107,255,.2)", color: "#c9c0ff" }}>
                    {view === "per_workspace" ? "ONE PRICE" : "MOST TEAMS"}
                  </span>
                ) : null}
              </div>
              <p style={{ margin: "8px 0 0", font: "400 15px/1.5 var(--fb)", color: "var(--tx2)" }}>{plan.blurb}</p>
              <p style={{ margin: "26px 0 0" }}>
                <span className={custom ? undefined : "mono"} style={custom ? { font: "600 46px var(--fd)", letterSpacing: "-.04em" } : { fontSize: 52, fontWeight: 600, letterSpacing: "-.05em" }}>
                  {price}
                </span>
              </p>
              <p style={{ margin: 0, font: "400 14px var(--fb)", color: "var(--tx3)" }}>
                {plan.unit}
                {yearly && !custom && plan.monthly !== "$0" ? ", billed yearly" : ""}
              </p>
              <Link className={`b ${plan.featured ? "b-l" : "b-g"}`} href={plan.href} style={{ marginTop: 24, width: "100%" }}>
                {plan.cta}
              </Link>
              <ul style={{ listStyle: "none", margin: "26px 0 0", padding: "22px 0 0", borderTop: "1px solid var(--ln)", display: "flex", flexDirection: "column", gap: 12, font: "400 15px/1.45 var(--fb)", color: "#dcd8ea" }}>
                {plan.features.map((feature) => (
                  <li key={feature} style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
                    <Check size={17} strokeWidth={2.2} color={plan.featured ? "#a99bff" : "#827d9a"} aria-hidden style={{ flex: "none", marginTop: 2 }} />
                    {feature}
                  </li>
                ))}
              </ul>
            </section>
          );
        })}
      </div>
      <TeamSize interval={yearly ? "year" : "month"} />
      <p style={{ margin: "18px 0 0", font: "400 13px var(--fb)", color: "var(--tx3)" }}>Sample prices for the design. Final pricing to be confirmed.</p>
    </div>
  );
}

/** Team-size slider: what Fleet (per person) and Studio (per workspace) cost, and which is cheaper. */
export function TeamSize({ interval }: { interval: Interval }) {
  const [team, setTeam] = useState(12);
  const calc = calculate(CALCULATOR_PLANS, team, interval);
  const [seat, space] = calc.plans;
  const comparison = calc.comparisons[0];
  const cheaperName = comparison?.cheaper === space.code ? space.name : seat.name;
  const billed = interval === "year" ? ", billed yearly" : "";
  const people = `${team} ${team === 1 ? "person" : "people"}`;
  let verdict: string;
  if (!space.available) verdict = `${space.name} fits up to ${space.seatCap} people, so ${seat.name} it is.`;
  else if (comparison?.cheaper === space.code) verdict = `${space.name} is cheaper. You save ${usd(comparison.savingsPerYearCents)} a year.`;
  else verdict = `${seat.name} is cheaper. You save ${usd(comparison?.savingsPerYearCents ?? 0)} a year.`;
  const box = { flex: "1 1 220px", padding: 18, borderRadius: 14, background: "var(--s1)" } as const;
  const win = { boxShadow: "inset 0 0 0 1px rgba(124,107,255,.55)" } as const;
  return (
    <section className="card" aria-labelledby="team-size-title" style={{ marginTop: 28, width: "100%", maxWidth: 820, padding: "clamp(22px,4vw,34px)", textAlign: "left" }}>
      <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "space-between", alignItems: "baseline", gap: 12 }}>
        <h2 id="team-size-title" style={{ margin: 0, font: "600 22px var(--fd)" }}>
          Per person or per workspace?
        </h2>
        <span className="mono tag" style={{ background: "var(--s3)", color: "var(--tx2)" }}>
          SAMPLE PRICES
        </span>
      </div>
      <label htmlFor="team-size" style={{ display: "block", marginTop: 18, font: "400 15px var(--fb)", color: "var(--tx2)" }}>
        Team size: <strong style={{ color: "var(--tx)" }}>{people}</strong>
      </label>
      <input
        id="team-size"
        type="range"
        min={1}
        max={SLIDER_MAX}
        step={1}
        value={team}
        onChange={(e) => setTeam(Number(e.target.value))}
        aria-valuetext={`${people}. ${cheaperName} is cheaper.`}
        style={{ width: "100%", marginTop: 10, accentColor: "var(--vi)", minHeight: 24 }}
      />
      <div style={{ display: "flex", flexWrap: "wrap", gap: 12, marginTop: 18 }}>
        <div style={{ ...box, ...(comparison?.cheaper === seat.code ? win : {}) }}>
          <p style={{ margin: 0, font: "600 16px var(--fd)" }}>{seat.name}, per person</p>
          <p className="mono" style={{ margin: "8px 0 0", fontSize: 28, fontWeight: 600 }}>
            {usd(seat.perMonthCents ?? 0)}
            <span style={{ fontSize: 14, color: "var(--tx3)" }}> a month{billed}</span>
          </p>
          <p style={{ margin: "4px 0 0", font: "400 13px var(--fb)", color: "var(--tx3)" }}>
            {usd(seat.unitPriceCents ?? 0)} x {people}
            {interval === "year" ? " a year" : ""}
          </p>
        </div>
        <div style={{ ...box, ...(comparison?.cheaper === space.code ? win : {}) }}>
          <p style={{ margin: 0, font: "600 16px var(--fd)" }}>{space.name}, per workspace</p>
          {space.available ? (
            <p className="mono" style={{ margin: "8px 0 0", fontSize: 28, fontWeight: 600 }}>
              {usd(space.perMonthCents ?? 0)}
              <span style={{ fontSize: 14, color: "var(--tx3)" }}> a month{billed}</span>
            </p>
          ) : (
            <p style={{ margin: "8px 0 0", font: "600 18px var(--fd)", color: "var(--tx2)" }}>Up to {space.seatCap} people</p>
          )}
          <p style={{ margin: "4px 0 0", font: "400 13px var(--fb)", color: "var(--tx3)" }}>One price for up to {space.seatCap} people</p>
        </div>
      </div>
      <p role="status" aria-live="polite" style={{ margin: "16px 0 0", font: "500 16px var(--fb)" }}>
        {verdict}
      </p>
      {comparison?.breakEven ? (
        <p style={{ margin: "4px 0 0", font: "400 13px var(--fb)", color: "var(--tx3)" }}>
          {space.name} costs less from {comparison.breakEven} people. Invites stop at {space.seatCap}, and we never charge for extra people without asking.
        </p>
      ) : null}
    </section>
  );
}
