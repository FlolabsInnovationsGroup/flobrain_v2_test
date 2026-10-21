import { ArrowRight, Cloud, EyeOff, Hand, Languages, Lock, Play, Plus, ShieldCheck, Users } from "lucide-react";
import Image from "next/image";
import Link from "next/link";

import { AuroraHorizon } from "@/components/v2/shell/AuroraHorizon";
import { BrandMark } from "@/components/v2/shell/BrandMark";
import { AUDIT, BUDDIES, DEVICES, FAQS, POLICY, SECURITY, STEPS } from "@/components/v2/site/content";
import { BuddyIcon } from "@/components/v2/site/BuddyIcon";
import { Crew, ModesShowcase } from "@/components/v2/site/Showcase";

export const metadata = { title: { absolute: "FloBrain, mission control for your team" } };

const TONE = {
  ok: { background: "rgba(43,217,126,.12)", color: "#2bd97e" },
  ask: { background: "rgba(255,181,71,.12)", color: "#ffc979" },
  no: { background: "rgba(255,77,109,.12)", color: "#ff8fa3" },
} as const;

function SplitHead({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
  return (
    <div className="split">
      <h2 id={id} className="d2">
        {title}
      </h2>
      <p className="lead">{children}</p>
    </div>
  );
}

export default function SiteHome() {
  return (
    <>
      {/* Hero */}
      <section aria-labelledby="hero-title" style={{ position: "relative", marginTop: -72, paddingTop: "calc(72px + clamp(72px,10vw,128px))", overflow: "hidden" }}>
        <AuroraHorizon top="clamp(560px,52vw,700px)" className="rise" />
        <div className="wrap" style={{ position: "relative", textAlign: "center", display: "flex", flexDirection: "column", alignItems: "center" }}>
          <Link className="pill up" href="#crew">
            Meet the buddies<i>8 NEW</i>
          </Link>
          <h1 id="hero-title" className="d1 up" style={{ marginTop: 26, animationDelay: ".08s" }}>
            Mission control
            <br />
            for your team.
          </h1>
          <p className="lead up" style={{ marginTop: 24, textAlign: "center", animationDelay: ".16s" }}>
            FloBrain is the AI operating system for teams. Rooms, meetings, tasks and a crew of AI buddies share one cockpit that knows your work, shows its sources and asks before it acts.
          </p>
          <div className="up" style={{ display: "flex", gap: 10, flexWrap: "wrap", justifyContent: "center", marginTop: 34, animationDelay: ".24s" }}>
            <Link className="b b-l" href="/contact">
              Book a demo
            </Link>
            <Link className="b b-g" href="/w/signin">
              <Play size={14} aria-hidden />
              Try the live demo
            </Link>
          </div>
        </div>
        <div className="wrap stage">
          <div className="frame tilt hero-shot">
            <Image
              src="/v2/shots/cockpit.webp"
              alt="The FloBrain cockpit: rooms on the left, the Space buddy answering with numbered sources and asking approval to create a task, and the impact score, tasks and buddies on the right."
              width={2880}
              height={1800}
              priority
              sizes="(max-width: 1240px) 100vw, 1200px"
            />
            <div className="fade-b" />
          </div>
          <div className="phone">
            <Image src="/v2/shots/mobile-home.webp" alt="FloBrain on a phone: timer, impact score, an approval request and a live room." width={780} height={1600} priority sizes="300px" />
          </div>
        </div>
      </section>

      {/* Principles */}
      <section aria-label="Principles" style={{ position: "relative", paddingTop: 28 }}>
        <div className="wrap trust">
          <span>
            <Lock size={17} color="#a99bff" aria-hidden />
            Zero data storage
          </span>
          <span>
            <EyeOff size={17} color="#a99bff" aria-hidden />
            No telemetry
          </span>
          <span>
            <ShieldCheck size={17} color="#a99bff" aria-hidden />
            AI stays scoped
          </span>
          <span>
            <Cloud size={17} color="#a99bff" aria-hidden />
            Runs in your cloud
          </span>
          <span>
            <Languages size={17} color="#a99bff" aria-hidden />
            Arabic and English
          </span>
        </div>
      </section>

      <section className="sec" aria-label="What FloBrain is">
        <div className="wrap">
          <p className="two">
            <b>One brain for the whole team.</b> Your rooms, meetings, tasks and AI buddies live in one cockpit, so nothing your team knows gets lost between apps, and every answer can point to where it came from.
          </p>
        </div>
      </section>

      {/* Modes */}
      <section id="product" className="sec" aria-labelledby="t-modes" style={{ paddingTop: 0 }}>
        <div className="wrap">
          <SplitHead id="t-modes" title="A cockpit that fits how you work.">
            Default shows everything at once. Focus hides the noise and holds notifications. Custom lets each person pin the views they live in.
          </SplitHead>
          <ModesShowcase />
        </div>
      </section>

      {/* Crew */}
      <section id="crew" className="sec" aria-labelledby="t-crew" style={{ background: "radial-gradient(60% 50% at 80% 40%,rgba(124,107,255,.10),transparent 70%)" }}>
        <div className="wrap">
          <SplitHead id="t-crew" title="Meet the crew.">
            Buddies are AI teammates with their own skills, knowledge and limits. Each one sees only what its room can see, and only what the person asking is allowed to open.
          </SplitHead>
          <Crew />
          <div style={{ marginTop: 16, display: "flex", flexWrap: "wrap", gap: 12, alignItems: "center", justifyContent: "space-between", padding: "20px 24px", borderRadius: 18, boxShadow: "inset 0 0 0 1px var(--ln2)", background: "var(--s1)" }}>
            <span style={{ font: "500 17px var(--fd)" }}>Need a different specialist? Build your own buddy in two minutes.</span>
            <Link className="b b-g" href="/w/signin" style={{ height: 42 }}>
              Open Buddy studio
              <ArrowRight size={15} aria-hidden />
            </Link>
          </div>
        </div>
      </section>

      {/* Meetings */}
      <section id="meetings" className="sec" aria-labelledby="t-meet">
        <div className="wrap">
          <SplitHead id="t-meet" title="Meetings that end with the work assigned.">
            No more notes nobody reads. Every call turns into a summary, the decisions, and tasks with owners, without anyone retyping a word.
          </SplitHead>
          <div className="frame hide-sm" style={{ marginTop: 44 }}>
            <Image
              src="/v2/shots/live-room.webp"
              alt="A live room: four people on video, a live transcript in Arabic and English, and an action item detected at minute 0:36."
              width={2880}
              height={1800}
              sizes="(max-width: 1240px) 100vw, 1200px"
            />
          </div>
          <ol className="steps" style={{ listStyle: "none", margin: "28px 0 0", padding: 0 }}>
            {STEPS.map((step, i) => (
              <li key={step.title} style={{ padding: "20px 0", borderTop: "1px solid var(--ln2)" }}>
                <span className="mono" style={{ display: "block", fontSize: 12, color: "var(--vi2)", marginBottom: 12 }}>
                  0{i + 1}
                </span>
                <b style={{ display: "block", font: "600 18px var(--fd)", letterSpacing: "-.02em" }}>{step.title}</b>
                <span style={{ display: "block", marginTop: 4, font: "400 15px/1.6 var(--fb)", color: "var(--tx2)" }}>{step.text}</span>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* Approvals */}
      <section className="sec" aria-labelledby="t-appr" style={{ background: "linear-gradient(180deg,transparent,rgba(255,181,71,.04) 50%,transparent)" }}>
        <div className="wrap">
          <SplitHead id="t-appr" title="AI that asks before it acts.">
            Buddies read, search and draft freely. Anything that changes data or leaves the team waits for a person. Admins set the rules per room, and every decision is on record.
          </SplitHead>
          <div className="grid3" style={{ marginTop: 44 }}>
            <div className="card" style={{ padding: 26 }}>
              <p className="k" style={{ margin: 0 }}>
                POLICY
              </p>
              <h3 className="d3" style={{ marginTop: 10 }}>
                You set the rules
              </h3>
              <dl style={{ margin: "20px 0 0", font: "400 14px var(--fb)" }}>
                {POLICY.map((row) => (
                  <div key={row.action} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 0", borderTop: "1px solid var(--ln)" }}>
                    <dt>{row.action}</dt>
                    <dd className="tag" style={{ margin: 0, ...TONE[row.tone] }}>
                      {row.rule}
                    </dd>
                  </div>
                ))}
              </dl>
            </div>
            <div className="card" style={{ padding: 26, boxShadow: "inset 0 0 0 1px rgba(255,181,71,.35)" }}>
              <p className="k" style={{ margin: 0, color: "#ffc979" }}>
                APPROVAL
              </p>
              <h3 className="d3" style={{ marginTop: 10 }}>
                A person decides
              </h3>
              <div className="appr" style={{ marginTop: 20 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <BuddyIcon buddy={BUDDIES[3]} size={28} radius={8} />
                  <b style={{ font: "600 14px var(--fd)" }}>Legal buddy</b>
                  <Hand size={15} color="#ffb547" aria-hidden style={{ marginLeft: "auto" }} />
                </div>
                <p style={{ margin: "10px 0 0", font: "400 14px/1.5 var(--fb)", color: "#e6e1f2" }}>Send the redlined NDA to the partner&apos;s counsel.</p>
                <div style={{ display: "flex", gap: 8, marginTop: 14 }} aria-hidden>
                  <span className="sb sb-a">Approve</span>
                  <span className="sb sb-g">Edit</span>
                </div>
              </div>
            </div>
            <div className="card" style={{ padding: 26 }}>
              <p className="k" style={{ margin: 0 }}>
                AUDIT
              </p>
              <h3 className="d3" style={{ marginTop: 10 }}>
                Everything is on record
              </h3>
              <ol style={{ listStyle: "none", margin: "20px 0 0", padding: 0, display: "flex", flexDirection: "column", gap: 14, font: "400 13.5px/1.45 var(--fb)", color: "var(--tx2)" }}>
                {AUDIT.map((row) => (
                  <li key={row.text} style={{ display: "grid", gridTemplateColumns: "44px 1fr", gap: 10 }}>
                    <span className="mono" style={{ fontSize: 11, color: "var(--tx3)", paddingTop: 2 }}>
                      {row.at}
                    </span>
                    {row.text}
                  </li>
                ))}
              </ol>
            </div>
          </div>
        </div>
      </section>

      {/* Impact */}
      <section className="sec" aria-labelledby="t-imp">
        <div className="wrap">
          <SplitHead id="t-imp" title="See the work, not the people.">
            Everyone gets an impact score and their own hours, tasks and focus rhythm. Leads see team totals, never messages or AI use. Anyone can keep their numbers personal.
          </SplitHead>
          <div className="wrapc" style={{ marginTop: 44, display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", gap: 14 }}>
            <div
              className="card"
              style={{
                padding: "clamp(28px,4vw,48px)",
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                textAlign: "center",
                background: "radial-gradient(70% 60% at 50% 30%,rgba(124,107,255,.18),transparent 70%),linear-gradient(180deg,var(--s2),var(--s1))",
              }}
            >
              <div className="ring" role="img" aria-label="Impact score 76 out of 100" style={{ width: 220, height: 220 }}>
                <b>76</b>
              </div>
              <p style={{ margin: "24px 0 0", font: "600 24px var(--fd)", letterSpacing: "-.02em" }}>Strong week</p>
              <p style={{ margin: "6px 0 0", font: "400 15px var(--fb)", color: "var(--tx2)" }}>4 tasks shipped, 18.5 focus hours, 6 day streak</p>
              <span className="mono" style={{ marginTop: 14, fontSize: 12, color: "var(--gr)", background: "rgba(43,217,126,.12)", padding: "5px 10px", borderRadius: 7 }}>
                +6 VS LAST WEEK
              </span>
            </div>
            <div style={{ display: "grid", gap: 14 }}>
              <div className="card" style={{ padding: 24, display: "flex", gap: 18, alignItems: "flex-start" }}>
                <EyeOff size={22} color="#a99bff" aria-hidden style={{ flex: "none" }} />
                <div>
                  <h3 className="d3" style={{ fontSize: 20 }}>
                    Yours by default
                  </h3>
                  <p style={{ margin: "6px 0 0", font: "400 15px/1.6 var(--fb)", color: "var(--tx2)" }}>Your hours, focus rhythm and AI use are visible to you and nobody else.</p>
                </div>
              </div>
              <div className="card" style={{ padding: 24, display: "flex", gap: 18, alignItems: "flex-start" }}>
                <Users size={22} color="#7fe3ff" aria-hidden style={{ flex: "none" }} />
                <div style={{ flex: 1 }}>
                  <h3 className="d3" style={{ fontSize: 20 }}>
                    Totals for leads
                  </h3>
                  <p style={{ margin: "6px 0 0", font: "400 15px/1.6 var(--fb)", color: "var(--tx2)" }}>Leads see tasks done, hours and blockers per team. Never messages.</p>
                  <div style={{ marginTop: 14, display: "flex", flexDirection: "column", gap: 8 }}>
                    {[
                      ["Design", 82, "var(--vi)", "191h"],
                      ["Engineering", 64, "var(--cy)", "148h"],
                      ["Marketing", 41, "var(--mg)", "96h"],
                    ].map(([name, width, color, hours]) => (
                      <div key={name as string} style={{ display: "grid", gridTemplateColumns: "100px 1fr 40px", gap: 10, alignItems: "center", font: "400 13px var(--fb)", color: "var(--tx2)" }}>
                        <span>{name}</span>
                        <span className="bar">
                          <i style={{ width: `${width}%`, background: color as string }} />
                        </span>
                        <span className="mono" style={{ textAlign: "right", color: "var(--tx)" }}>
                          {hours}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
              <div className="card" style={{ padding: "20px 24px", display: "flex", gap: 16, alignItems: "center", justifyContent: "space-between" }}>
                <span style={{ font: "500 16px var(--fd)" }}>Keep my insights personal</span>
                <span role="img" aria-label="Setting shown on" style={{ width: 46, height: 26, borderRadius: 99, background: "var(--vi)", position: "relative", flex: "none" }}>
                  <span style={{ position: "absolute", right: 3, top: 3, width: 20, height: 20, borderRadius: "50%", background: "#fff" }} />
                </span>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Everywhere */}
      <section className="sec" aria-labelledby="t-ev" style={{ overflow: "hidden" }}>
        <div className="wrap split" style={{ alignItems: "center" }}>
          <div>
            <h2 id="t-ev" className="d2">
              Every where, all at once.
            </h2>
            <p className="lead" style={{ marginTop: 22 }}>
              The memory and buddies you use on the web follow you to your phone and your watch, and to the robots and devices FloBrain already runs on. One brain, infinite possibilities.
            </p>
          </div>
          <div className="orbit" role="img" aria-label="FloBrain at the center, connected to wearables, mobile, web, robotics, IoT and enterprise systems">
            <div className="r" style={{ inset: 0 }} />
            <div className="r" style={{ inset: "16%" }} />
            <div className="r" style={{ inset: "32%", background: "radial-gradient(closest-side,rgba(124,107,255,.25),transparent)" }} />
            <div className="sweep" />
            <span style={{ position: "absolute", left: "50%", top: "50%", transform: "translate(-50%,-50%)", filter: "drop-shadow(0 0 30px rgba(124,107,255,.9))" }}>
              <BrandMark size={76} />
            </span>
            {DEVICES.map((device) => {
              const Icon = device.icon;
              return (
                <div key={device.name} className="dev" style={{ left: `${device.x}%`, top: `${device.y}%` }}>
                  <span>
                    <Icon size={22} color="#c9c0ff" aria-hidden />
                  </span>
                  {device.name}
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* Arabic */}
      <section className="sec" aria-labelledby="t-ar" style={{ background: "linear-gradient(90deg,#290036 0%,#070014 100%)", borderBlock: "1px solid var(--ln)" }}>
        <div className="wrap split" style={{ alignItems: "center" }}>
          <div>
            <h2 id="t-ar" className="d2">
              Built for Arabic, not translated into it.
            </h2>
            <p className="lead" style={{ marginTop: 22 }}>
              The whole cockpit works right to left. People write in the language they think in, and everyone reads it in theirs. Search, meetings and buddies understand both.
            </p>
            <p className="ar" lang="ar" dir="rtl" style={{ margin: "30px 0 0", font: "700 clamp(30px,3.6vw,48px)/1.3 var(--fa)", textAlign: "left" }}>
              عقل واحد لفريقك كله.
            </p>
          </div>
          <div className="card ar" lang="ar" dir="rtl" style={{ padding: 24, display: "flex", flexDirection: "column", gap: 16, font: "400 16px/1.7 var(--fa)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <b style={{ fontSize: 18 }}>غرفة الإطلاق</b>
              <span className="chip mono" dir="ltr">
                AR | EN
              </span>
            </div>
            {[
              ["ليلى منصور", "إصلاح تسجيل الدخول في المراجعة. متوقع يوم الخميس.", "linear-gradient(135deg,#F59E0B,#EF4444)", "LM"],
              ["عمر خالد", "محتاجين جهاز أندرويد للتجربة.", "linear-gradient(135deg,#8B5CF6,#6366F1)", "OK"],
            ].map(([name, text, bg, code]) => (
              <div key={code} style={{ display: "flex", gap: 12 }}>
                <span aria-hidden style={{ flex: "none", display: "grid", placeItems: "center", width: 34, height: 34, borderRadius: 10, background: bg, font: "600 12px var(--fd)" }}>
                  {code}
                </span>
                <div>
                  <b>{name}</b>
                  <div style={{ color: "#dcd8ea" }}>{text}</div>
                </div>
              </div>
            ))}
            <div style={{ display: "flex", gap: 12 }}>
              <BuddyIcon buddy={BUDDIES[5]} size={34} radius={10} />
              <p className="bub" style={{ margin: 0, fontFamily: "var(--fa)", borderRadius: "16px 4px 16px 16px" }}>
                العائق الوحيد هو مشكلة تسجيل الدخول على أندرويد <span className="cite">1</span>. أعمل مهمة لعمر؟
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* Security */}
      <section id="security" className="sec" aria-labelledby="t-sec">
        <div className="wrap">
          <SplitHead id="t-sec" title="Your data, your cloud, your rules.">
            FloBrain was built for companies that can&apos;t send their work to someone else&apos;s servers. The defaults are strict, and admins can make them stricter.
          </SplitHead>
          <ul className="grid3" style={{ listStyle: "none", padding: 0, marginTop: 44, gap: 1, background: "var(--ln2)", borderRadius: 22, overflow: "hidden", boxShadow: "inset 0 0 0 1px var(--ln2)" }}>
            {SECURITY.map((item) => {
              const Icon = item.icon;
              return (
                <li key={item.title} style={{ padding: 28, background: "var(--s1)" }}>
                  <Icon size={22} color="#a99bff" aria-hidden />
                  <h3 style={{ margin: "18px 0 0", font: "600 18px var(--fd)", letterSpacing: "-.02em" }}>{item.title}</h3>
                  <p style={{ margin: "8px 0 0", font: "400 15px/1.6 var(--fb)", color: "var(--tx2)" }}>{item.text}</p>
                </li>
              );
            })}
          </ul>
        </div>
      </section>

      {/* Pricing teaser */}
      <section className="sec" aria-labelledby="t-pr" style={{ paddingTop: 0 }}>
        <div className="wrap">
          <div
            className="card"
            style={{
              padding: "clamp(28px,5vw,56px)",
              display: "flex",
              flexWrap: "wrap",
              gap: 24,
              alignItems: "center",
              justifyContent: "space-between",
              background: "radial-gradient(60% 120% at 100% 0%,rgba(0,212,255,.12),transparent 60%),radial-gradient(60% 120% at 0% 100%,rgba(204,52,255,.12),transparent 60%),var(--s1)",
            }}
          >
            <div style={{ maxWidth: 620 }}>
              <h2 id="t-pr" className="d2" style={{ fontSize: "clamp(30px,3.4vw,46px)" }}>
                Start with your crew. Grow to a fleet.
              </h2>
              <p className="lead" style={{ marginTop: 14 }}>
                Free for small teams. Pay per person when you need more buddies, meetings and admin controls.
              </p>
            </div>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              <Link className="b b-l" href="/v2/pricing">
                See pricing
              </Link>
              <Link className="b b-g" href="/contact">
                Talk to us
              </Link>
            </div>
          </div>
        </div>
      </section>

      {/* FAQ */}
      <section className="sec faq" aria-labelledby="t-faq" style={{ paddingTop: 0 }}>
        <div className="wrap faqg" style={{ display: "grid", gridTemplateColumns: "minmax(0,.7fr) minmax(0,1.3fr)", gap: "clamp(24px,5vw,80px)" }}>
          <h2 id="t-faq" className="d2" style={{ fontSize: "clamp(32px,3.6vw,48px)" }}>
            Questions, answered.
          </h2>
          <div>
            {FAQS.map((item, i) => (
              <details key={item.q} open={i === 0}>
                <summary>
                  {item.q}
                  <Plus size={22} aria-hidden />
                </summary>
                <p>{item.a}</p>
              </details>
            ))}
            <div style={{ borderTop: "1px solid var(--ln2)" }} />
          </div>
        </div>
      </section>

      {/* Final call */}
      <section aria-labelledby="t-cta" style={{ position: "relative", overflow: "hidden", paddingBlock: "clamp(110px,14vw,200px) clamp(140px,16vw,240px)", textAlign: "center" }}>
        <AuroraHorizon top="80%" />
        <div className="wrap" style={{ position: "relative", display: "flex", flexDirection: "column", alignItems: "center" }}>
          <span style={{ filter: "drop-shadow(0 0 34px rgba(124,107,255,.9))" }}>
            <BrandMark size={72} />
          </span>
          <h2 id="t-cta" className="d1" style={{ marginTop: 28, fontSize: "clamp(40px,6vw,84px)" }}>
            Give your team
            <br />
            one brain.
          </h2>
          <p className="lead" style={{ marginTop: 22, textAlign: "center" }}>
            A 30 minute call with your own use case, or the live demo right now.
          </p>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", justifyContent: "center", marginTop: 32 }}>
            <Link className="b b-l" href="/contact">
              Book a demo
            </Link>
            <Link className="b b-g" href="/w/signin">
              <Play size={14} aria-hidden />
              Try the live demo
            </Link>
          </div>
          <p className="mono" style={{ marginTop: 40, fontSize: 12, color: "#c9c0ff", letterSpacing: ".08em" }}>
            LIVE LONG AND PROSPER
          </p>
        </div>
      </section>
    </>
  );
}
