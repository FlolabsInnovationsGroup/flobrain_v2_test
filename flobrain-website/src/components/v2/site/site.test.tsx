import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BUDDIES, PLANS } from "./content";
import { Plans } from "./Plans";
import { Crew, ModesShowcase } from "./Showcase";

describe("V2 site", () => {
  it("switches plan prices between yearly and monthly", () => {
    render(<Plans />);
    const fleet = PLANS.find((p) => p.featured)!;
    expect(screen.getByText(fleet.yearly)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "Monthly" }));
    expect(screen.getByRole("radio", { name: "Monthly" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByText(fleet.monthly)).toBeInTheDocument();
  });

  it("shows the chosen buddy's conversation and moves with the arrow keys", () => {
    render(<Crew />);
    const tabs = screen.getAllByRole("tab");
    expect(tabs).toHaveLength(BUDDIES.length);
    fireEvent.click(tabs[0]);
    expect(screen.getByText(BUDDIES[0].answer)).toBeInTheDocument();
    fireEvent.keyDown(tabs[0], { key: "ArrowRight" });
    expect(tabs[1]).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText(BUDDIES[1].answer)).toBeInTheDocument();
  });

  it("swaps the cockpit shot when a layout tab is picked", () => {
    render(<ModesShowcase />);
    fireEvent.click(screen.getByRole("tab", { name: "Focus" }));
    expect(screen.getByRole("tab", { name: "Focus" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("img", { name: /Focus mode/ })).toBeInTheDocument();
  });
});
