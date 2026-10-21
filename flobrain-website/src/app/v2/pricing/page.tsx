import { Check } from "lucide-react";
import Link from "next/link";

import { COMPARE } from "@/components/v2/site/content";
import { Plans } from "@/components/v2/site/Plans";

export const metadata = { title: "Pricing" };

function Cell({ value }: { value: string }) {
  if (value === "yes") return <Check size={18} strokeWidth={2.2} color="#a99bff" aria-label="Included" />;
  if (value === "") return <span aria-label="Not included" style={{ color: "var(--tx3)" }}>-</span>;
  return <span>{value}</span>;
}

export default function PricingPage() {
  return (
    <>
      <section aria-labelledby="pricing-title" style={{ position: "relative", paddingTop: "clamp(64px,8vw,110px)" }}>
        <div className="wrap" style={{ textAlign: "center", display: "flex", flexDirection: "column", alignItems: "center" }}>
          <h1 id="pricing-title" className="d1" style={{ fontSize: "clamp(40px,6vw,80px)" }}>
            Pricing that scales
            <br />
            with your crew.
          </h1>
          <p className="lead" style={{ marginTop: 22, textAlign: "center" }}>
            Every plan includes rooms, buddies and the cockpit. Upgrade when you need meetings, approvals and your own cloud.
          </p>
        </div>
        <div className="wrap">
          <Plans />
        </div>
      </section>

      <section className="sec" aria-labelledby="compare-title">
        <div className="wrap">
          <h2 id="compare-title" className="d2" style={{ fontSize: "clamp(30px,3.4vw,46px)" }}>
            Compare plans
          </h2>
          <div className="cmpw" style={{ marginTop: 32 }}>
            <table className="cmp">
              <thead>
                <tr>
                  <th scope="col" style={{ width: "34%" }}>
                    <span className="sr-only">Feature</span>
                  </th>
                  <th scope="col">Crew</th>
                  <th scope="col">Fleet</th>
                  <th scope="col">Mission</th>
                </tr>
              </thead>
              <tbody>
                {COMPARE.map(([feature, ...values]) => (
                  <tr key={feature}>
                    <th scope="row">{feature}</th>
                    {values.map((value, i) => (
                      <td key={i}>
                        <Cell value={value} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section className="sec" style={{ paddingTop: 0 }}>
        <div className="wrap">
          <div className="card" style={{ padding: "clamp(28px,5vw,56px)", display: "flex", flexWrap: "wrap", gap: 24, alignItems: "center", justifyContent: "space-between" }}>
            <div style={{ maxWidth: 620 }}>
              <h2 className="d2" style={{ fontSize: "clamp(28px,3vw,40px)" }}>
                Running a school, NGO or startup program?
              </h2>
              <p className="lead" style={{ marginTop: 12 }}>
                We offer Fleet at a discount for education and non-profits. Tell us about your team.
              </p>
            </div>
            <Link className="b b-l" href="/contact">
              Apply for a discount
            </Link>
          </div>
        </div>
      </section>
    </>
  );
}
