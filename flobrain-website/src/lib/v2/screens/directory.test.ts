import { describe, expect, it } from "vitest";

import { contactVisible, filterDirectory } from "./directory";

const members = [
  { id: "1", username: "Ada", email: "ada@org.test", teams: ["Team A"] },
  { id: "2", username: "Ben", teams: ["Team B"] },
];

describe("directory logic", () => {
  it("filters by name, email, or team", () => {
    expect(filterDirectory(members, "ada")).toHaveLength(1);
    expect(filterDirectory(members, "team b")[0].id).toBe("2");
    expect(filterDirectory(members, "")).toHaveLength(2);
  });

  it("hides contact unless present", () => {
    expect(contactVisible(members[0])).toBe(true);
    expect(contactVisible(members[1])).toBe(false);
  });
});
