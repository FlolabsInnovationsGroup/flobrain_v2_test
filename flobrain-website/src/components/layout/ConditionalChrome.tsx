"use client";

import { usePathname } from "next/navigation";

import Footer from "@/components/layout/footer";
import Navbar from "@/components/layout/navbar";

export function ConditionalChrome({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  // V2 owns its chrome: the workspace (/w) and the V2 site (/v2) bring their own navigation.
  if (pathname?.startsWith("/w") || pathname === "/v2" || pathname?.startsWith("/v2/")) {
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
