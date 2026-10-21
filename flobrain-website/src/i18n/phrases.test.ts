import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { AR_PHRASES, PHRASES, translate } from "./phrases";

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? files(path) : /\.tsx?$/.test(name) && !/\.test\./.test(name) ? [path] : [];
  });
}

/** Every literal passed to tr("…") or tr('…') in the workspace screens. */
function usedPhrases(): string[] {
  const roots = ["src/app/w", "src/app/verify", "src/app/p", "src/components/v2"];
  const found = new Set<string>();
  for (const file of roots.flatMap((r) => files(r))) {
    const source = readFileSync(file, "utf8");
    for (const m of source.matchAll(/\btr\(\s*"((?:[^"\\]|\\.)*)"/g)) found.add(JSON.parse(`"${m[1]}"`));
  }
  return [...found];
}

describe("Arabic screen copy", () => {
  it("drops a context prefix, even one with a space", () => {
    expect(translate("en", "room tab|AI")).toBe("AI");
    expect(translate("en", "state|Open")).toBe("Open");
  });

  it("fills variables and falls back to English", () => {
    expect(translate("en", "{n} messages", { n: 3 })).toBe("3 messages");
    expect(translate("ar", "A sentence nobody translated")).toBe("A sentence nobody translated");
    expect(translate("en", "state|Open")).toBe("Open");
    expect(translate("ar", "state|Open")).not.toBe(translate("ar", "Open"));
  });

  it("has an Arabic line for every tr() string", () => {
    const missing = usedPhrases().filter((p) => !(p in AR_PHRASES));
    expect(missing).toEqual([]);
  });

  it("keeps the same {placeholders} in every language", () => {
    const vars = (s: string) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
    for (const [lang, map] of Object.entries(PHRASES)) {
      const broken = Object.entries(map).filter(([en, out]) => vars(en).join() !== vars(out).join());
      expect(broken, lang).toEqual([]);
    }
  });

  it("has Turkish, French and Portuguese for everything Arabic has", () => {
    for (const lang of ["tr", "fr", "pt"] as const) {
      const missing = Object.keys(AR_PHRASES).filter((k) => !(k in PHRASES[lang]));
      expect(missing.length, `${lang} is missing ${missing.slice(0, 5).join(" | ")}`).toBe(0);
    }
  });
});
