import { useSyncExternalStore } from "react";

import ar from "../../messages/ar.json";
import en from "../../messages/en.json";
import fr from "../../messages/fr.json";
import pt from "../../messages/pt.json";
import tr from "../../messages/tr.json";

export type V2Locale = "en" | "ar" | "tr" | "fr" | "pt";

/** Languages people can pick, by their own name. */
export const LOCALES: { code: V2Locale; name: string }[] = [
  { code: "en", name: "English" },
  { code: "ar", name: "العربية" },
  { code: "tr", name: "Türkçe" },
  { code: "fr", name: "Français" },
  { code: "pt", name: "Português" },
];

const catalogs: Record<V2Locale, unknown> = { en, ar, tr, fr, pt };

function isLocale(value: unknown): value is V2Locale {
  return typeof value === "string" && value in catalogs;
}

export function getLocale(): V2Locale {
  if (typeof document !== "undefined") {
    const stored = window.localStorage.getItem("flobrain_v2_locale");
    if (isLocale(stored)) return stored;
    const lang = document.documentElement.lang;
    if (isLocale(lang)) return lang;
  }
  return "en";
}

export function dirFor(locale: V2Locale): "ltr" | "rtl" {
  return locale === "ar" ? "rtl" : "ltr";
}

function lookup(catalog: unknown, key: string): string | null {
  let node: unknown = catalog;
  for (const part of key.split(".")) {
    if (node && typeof node === "object" && part in node) {
      node = (node as Record<string, unknown>)[part];
    } else {
      return null;
    }
  }
  return typeof node === "string" ? node : null;
}

/** A catalog string; a line missing in the chosen language falls back to English, then to the key. */
export function t(locale: V2Locale, key: string): string {
  return lookup(catalogs[locale], key) ?? lookup(catalogs.en, key) ?? key;
}

/** Switch the workspace language; the page reloads so every screen picks it up. */
export function setLocale(locale: V2Locale) {
  window.localStorage.setItem("flobrain_v2_locale", locale);
  document.documentElement.lang = locale;
  document.documentElement.dir = dirFor(locale);
  window.location.reload();
}

const noop = () => () => undefined;

/**
 * The locale for rendering. The server always renders English, then the client switches,
 * so hydration never mismatches.
 */
export function useLocale(): V2Locale {
  return useSyncExternalStore(noop, getLocale, () => "en");
}
