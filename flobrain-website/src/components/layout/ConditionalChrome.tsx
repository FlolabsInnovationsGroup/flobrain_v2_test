"use client";

import { usePathname } from "next/navigation";

import Footer from "@/components/layout/footer";
import Navbar from "@/components/layout/navbar";

export function ConditionalChrome({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  // V2 owns its chrome: the workspace (/w), the V2 site (/v2) and public trust pages (/trust) bring their own.
  if (pathname?.startsWith("/w") || pathname === "/v2" || pathname?.startsWith("/v2/") || pathname?.startsWith("/trust/")) {
    return <div className="flex-1">{children}</div>;
  }
  return (
    <>
      <Navbar />
      <div className="flex-1">{children}</div>
      <Footer />
    </>
  );
}
