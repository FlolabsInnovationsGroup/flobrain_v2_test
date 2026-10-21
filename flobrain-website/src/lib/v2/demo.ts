import { api } from "./api";
import { storeV2Tokens } from "./client";

export type DemoRole = { key: string; name: string; org_role: string; description: string; email: string };
export type DemoInfo = { enabled: boolean; org_slug?: string; roles?: DemoRole[] };

export async function demoInfo(): Promise<DemoInfo> {
  try {
    return await api.get<DemoInfo>("/demo");
  } catch {
    return { enabled: false };
  }
}

/** Sign in as a demo role and return the workspace path to open. */
export async function demoSignIn(role: string, landing = ""): Promise<string> {
  const res = await api.post<{ access: string; refresh: string; user_id: string; must_change_password: boolean; org_slug: string }>(
    "/demo/signin",
    { role },
  );
  storeV2Tokens(res);
  if (typeof window !== "undefined") window.localStorage.setItem("flobrain_demo_role", role);
  return `/w/${res.org_slug}${landing}`;
}

export async function demoReset(): Promise<void> {
  await api.post("/demo/reset");
}

/** What each role can try first: shown on the role picker and the tour. */
export const ROLE_HIGHLIGHTS: Record<string, string[]> = {
  owner: ["Set the AI policy and billing", "Turn on SSO and provisioning", "Export the org's memory"],
  admin: ["Approve marketplace listings", "Manage members and access", "See audit and support sessions"],
  lead: ["Generate the weekly team report", "Run the Monday release-notes agent", "Unblock Youssef's Android task"],
  member: ["Ask a question across rooms and docs", "Approve the task your buddy proposed", "Make a short video in Content Studio"],
};

export const ROLE_INITIALS: Record<string, string> = { owner: "NH", admin: "OK", lead: "LM", member: "YA" };
