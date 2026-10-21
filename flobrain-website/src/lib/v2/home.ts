import { v2Client } from "@/lib/v2/client";

/** Only same-site workspace paths are allowed after sign-in, never another origin (review 15-16: normalise first). */
export function safeNext(next: string | null): string | null {
  if (!next || !next.startsWith("/") || next.startsWith("//") || /[\\\s]/.test(next)) return null;
  try {
    const origin = typeof window === "undefined" ? "http://localhost" : window.location.origin;
    const url = new URL(next, origin);
    if (url.origin !== origin || !url.pathname.startsWith("/w/") || url.pathname.startsWith("//")) return null;
    return url.pathname + url.search + url.hash;
  } catch {
    return null;
  }
}

/** The first workspace the signed-in person belongs to. */
export async function homePath(): Promise<string> {
  try {
    const orgs = await v2Client().orgs();
    return orgs[0] ? `/w/${encodeURIComponent(orgs[0].slug)}` : "/w/signin";
  } catch {
    return "/w/signin";
  }
}
