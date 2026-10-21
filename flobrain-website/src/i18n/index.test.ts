import { describe, expect, it } from "vitest";

import { dirFor, t } from "./index";

describe("v2 i18n", () => {
  it("returns English and Arabic strings", () => {
    expect(t("en", "workspace.empty")).toBe("No data yet");
    expect(t("ar", "workspace.empty")).toBe("لا توجد بيانات بعد");
    expect(dirFor("ar")).toBe("rtl");
  });
});
