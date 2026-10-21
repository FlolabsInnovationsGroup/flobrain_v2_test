import type { Metadata, Viewport } from "next";

export const metadata: Metadata = {
  manifest: "/manifest.webmanifest",
  appleWebApp: { capable: true, title: "FloBrain", statusBarStyle: "black-translucent" },
  icons: { apple: "/icons/flobrain-192.png" },
};

export const viewport: Viewport = { themeColor: "#08070f" };

export default function WorkspaceRootLayout({ children }: { children: React.ReactNode }) {
  return children;
}
