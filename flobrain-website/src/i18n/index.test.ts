import { describe, expect, it } from "vitest";

import { dirFor, t } from "./index";

describe("v2 i18n", () => {
  it("returns English and Arabic strings", () => {
    expect(t("en", "workspace.empty")).toBe("No data yet");
    expect(t("ar", "workspace.empty")).toBe("لا توجد بيانات بعد");
    expect(dirFor("ar")).toBe("rtl");
  });
});

function keys(node: unknown, prefix = ""): string[] {
  if (!node || typeof node !== "object") return [prefix];
  return Object.entries(node as Record<string, unknown>).flatMap(([k, v]) => keys(v, prefix ? `${prefix}.${k}` : k));
}

describe("catalog parity", () => {
  it("has every English key in every language", async () => {
    const en = keys((await import("../../messages/en.json")).default).sort();
    for (const lang of ["ar", "tr", "fr", "pt"]) {
      const other = keys((await import(`../../messages/${lang}.json`)).default).sort();
      expect(other, lang).toEqual(en);
    }
  });

  it("falls back to English for a missing line", () => {
    expect(t("tr", "workspace.empty")).toBeTruthy();
    expect(t("fr", "no.such.key")).toBe("no.such.key");
  });
});
