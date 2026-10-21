"use client";

import { Menu, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { BrandMark } from "@/components/v2/shell/BrandMark";

const LINKS = [
  { href: "/v2#product", label: "Product" },
  { href: "/v2#crew", label: "Buddies" },
  { href: "/v2#meetings", label: "Meetings" },
  { href: "/v2#security", label: "Security" },
  { href: "/v2/pricing", label: "Pricing" },
  { href: "/status", label: "Status" },
];

export function SiteNav() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && setOpen(false);
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [open]);

  return (
    <>
      <header className="nav">
        <Link href="/v2" className="flex items-center gap-2.5" aria-label="FloBrain home">
          <BrandMark size={26} />
          <b style={{ font: "600 18px var(--fd)", letterSpacing: "-0.03em" }}>FloBrain</b>
        </Link>
        <nav className="links" aria-label="Main">
          {LINKS.map((link) => (
            <Link key={link.href} href={link.href}>
              {link.label}
            </Link>
          ))}
        </nav>
        <span className="flex-1" />
        <Link className="hide-md" href="/w/signin" style={{ font: "500 14px var(--fd)", color: "var(--tx2)", padding: "0 10px" }}>
          Sign in
        </Link>
        <Link className="b b-l" href="/contact" style={{ height: 40, padding: "0 16px", fontSize: 14, borderRadius: 10 }}>
          Book a demo
        </Link>
        <button
          type="button"
          className="burger b b-g"
          style={{ width: 40, height: 40, padding: 0, borderRadius: 10 }}
          aria-label={open ? "Close menu" : "Open menu"}
          aria-expanded={open}
          aria-controls="site-menu"
          onClick={() => setOpen((v) => !v)}
        >
          {open ? <X size={18} aria-hidden /> : <Menu size={18} aria-hidden />}
        </button>
      </header>
      {open ? (
        <nav id="site-menu" className="menu" aria-label="Menu">
          {LINKS.map((link) => (
            <Link key={link.href} href={link.href} onClick={() => setOpen(false)}>
              {link.label}
            </Link>
          ))}
          <Link href="/w/signin" onClick={() => setOpen(false)}>
            Sign in
          </Link>
        </nav>
      ) : null}
    </>
  );
}

export function SiteFooter() {
  const col = (title: string, links: [string, string][]) => (
    <nav aria-label={title} className="flex flex-col gap-3">
      <b style={{ font: "500 13px var(--fd)", color: "var(--tx3)" }}>{title}</b>
      {links.map(([label, href]) => (
        <Link key={label} href={href}>
          {label}
        </Link>
      ))}
    </nav>
  );
  return (
    <footer className="foot" style={{ borderTop: "1px solid var(--ln)", background: "var(--void)", overflow: "hidden" }}>
      <div className="wrap footg" style={{ paddingBlock: "64px 24px", display: "grid", gridTemplateColumns: "minmax(0,1.4fr) repeat(4,minmax(0,1fr))", gap: 32 }}>
        <div>
          <div className="flex items-center gap-2.5">
            <BrandMark size={28} />
            <b style={{ font: "600 18px var(--fd)" }}>FloBrain</b>
          </div>
          <p style={{ margin: "14px 0 0", maxWidth: 280, font: "400 14px/1.6 var(--fb)", color: "var(--tx3)" }}>
            The AI operating system for your team. Made by FloLabs.
          </p>
          <Link
            href="/status"
            className="mono"
            style={{ marginTop: 18, display: "inline-flex", alignItems: "center", gap: 8, height: 30, padding: "0 10px", borderRadius: 8, boxShadow: "inset 0 0 0 1px var(--ln2)", fontSize: 12, color: "var(--tx2)" }}
          >
            <span className="live-dot" />
            SYSTEM STATUS
          </Link>
        </div>
        {col("Product", [
          ["Cockpit", "/v2#product"],
          ["Buddies", "/v2#crew"],
          ["Meetings", "/v2#meetings"],
          ["Pricing", "/v2/pricing"],
        ])}
        {col("Company", [
          ["About FloLabs", "/"],
          ["Contact", "/contact"],
        ])}
        {col("Trust", [
          ["Security", "/v2#security"],
          ["Status", "/status"],
        ])}
        {col("Start", [
          ["Live demo", "/w/signin"],
          ["Sign in", "/w/signin"],
          ["Book a demo", "/contact"],
        ])}
      </div>
      <p className="wordmark" aria-hidden>
        FloBrain
      </p>
      <div
        className="wrap"
        style={{ paddingBlock: "20px 28px", display: "flex", flexWrap: "wrap", gap: 12, justifyContent: "space-between", font: "400 13px var(--fb)", color: "var(--tx3)", borderTop: "1px solid var(--ln)" }}
      >
        <span>© 2026 FloLabs Innovations Group</span>
        <span>Live long and prosper.</span>
      </div>
    </footer>
  );
}
