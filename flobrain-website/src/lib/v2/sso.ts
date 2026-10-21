const KEY = "flobrain_sso_client_nonce";

/** A random value this browser keeps for one SSO sign-in; the code only works with it. */
export function newClientNonce(): string {
  const bytes = new Uint8Array(24);
  crypto.getRandomValues(bytes);
  const nonce = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  window.sessionStorage.setItem(KEY, nonce);
  return nonce;
}

export function takeClientNonce(): string {
  const nonce = window.sessionStorage.getItem(KEY) || "";
  window.sessionStorage.removeItem(KEY);
  return nonce;
}

export const SSO_ERRORS: Record<string, string> = {
  invalid_state: "This sign-in link has expired or was already used. Start again.",
  email_not_verified: "Your identity provider has not verified your email.",
  domain_not_verified: "Your email's domain is not verified for this organization.",
  not_a_member: "You are not an active member of this organization. Ask an admin to add you.",
  platform_admin: "Platform staff accounts can't use an organization's SSO.",
  disabled: "SSO is switched off for this organization.",
};
