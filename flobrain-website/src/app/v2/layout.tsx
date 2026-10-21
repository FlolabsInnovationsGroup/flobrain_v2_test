import type { Metadata, Viewport } from "next";

import { SiteFooter, SiteNav } from "@/components/v2/site/SiteChrome";
import "@/styles/v2-tokens.css";
import "@/styles/v2-site.css";

export const metadata: Metadata = {
  title: { default: "FloBrain, mission control for your team", template: "%s | FloBrain" },
  description:
    "FloBrain is the AI operating system for teams. Rooms, meetings, tasks and a crew of AI buddies in one cockpit that knows your work, shows its sources and asks before it acts.",
};

export const viewport: Viewport = { themeColor: "#08070f" };

export default function SiteLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="v2-site">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-[70]">
        Skip to content
      </a>
      <SiteNav />
      <main id="main">{children}</main>
      <SiteFooter />
    </div>
  );
}
