"use client";

import { Check } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { PLANS } from "./content";

export function Plans() {
  const [yearly, setYearly] = useState(true);
  return (
    <div style={{ marginTop: 40, display: "flex", flexDirection: "column", alignItems: "center" }}>
      <div className="tabbar" role="radiogroup" aria-label="Billing">
        <button type="button" role="radio" aria-checked={!yearly} onClick={() => setYearly(false)}>
          Monthly
        </button>
        <button type="button" role="radio" aria-checked={yearly} onClick={() => setYearly(true)}>
          Yearly
          <span className="mono" style={{ fontSize: 10.5, color: "var(--gr)" }}>
            SAVE 17%
          </span>
        </button>
      </div>
      <div className="plans" style={{ marginTop: 36, width: "100%", textAlign: "left" }}>
        {PLANS.map((plan) => {
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
                    MOST TEAMS
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
      <p style={{ margin: "18px 0 0", font: "400 13px var(--fb)", color: "var(--tx3)" }}>Sample prices for the design. Final pricing to be confirmed.</p>
    </div>
  );
}
