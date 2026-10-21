import ar from "../../messages/ar.json";
import en from "../../messages/en.json";

export type V2Locale = "en" | "ar";

const catalogs = { en, ar } as const;

export function getLocale(): V2Locale {
  if (typeof document !== "undefined") {
    const stored = window.localStorage.getItem("flobrain_v2_locale");
    if (stored === "ar" || stored === "en") return stored;
    if (document.documentElement.lang === "ar") return "ar";
  }
  return "en";
}

export function dirFor(locale: V2Locale): "ltr" | "rtl" {
  return locale === "ar" ? "rtl" : "ltr";
}

export function t(locale: V2Locale, key: string): string {
  const parts = key.split(".");
  let node: unknown = catalogs[locale];
  for (const part of parts) {
    if (node && typeof node === "object" && part in node) {
      node = (node as Record<string, unknown>)[part];
    } else {
      return key;
    }
  }
  return typeof node === "string" ? node : key;
}
