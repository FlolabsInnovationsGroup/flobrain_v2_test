import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BUDDIES, COMPARE, COMPARE_PLANS, PLANS, WORKSPACE_PLANS } from "./content";
import { Plans, TeamSize } from "./Plans";
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

  it("switches to the flat per-workspace prices and moves with the arrow keys", () => {
    render(<Plans />);
    const studio = WORKSPACE_PLANS.find((p) => p.featured)!;
    expect(studio.yearly).toBe("$165");
    expect(screen.queryByRole("heading", { name: "Studio" })).toBeNull();
    const perPerson = screen.getByRole("radio", { name: "Per person" });
    expect(perPerson).toHaveAttribute("tabindex", "0");
    fireEvent.keyDown(perPerson, { key: "ArrowRight" });
    expect(screen.getByRole("radio", { name: "Per workspace" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("heading", { name: "Studio" })).toBeInTheDocument();
    const card = () => within(screen.getByRole("region", { name: "Studio" }));
    expect(card().getByText(studio.yearly)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "Monthly" }));
    expect(card().getByText(studio.monthly)).toBeInTheDocument();
    expect(screen.getAllByText(/Sample prices/i).length).toBeGreaterThan(0);
  });

  it("team-size slider shows which option is cheaper, up to the cap", () => {
    render(<TeamSize interval="month" />);
    const slider = screen.getByRole("slider", { name: /Team size/ });
    expect(slider).toHaveAttribute("aria-valuetext", "12 people. Fleet is cheaper.");
    expect(screen.getByRole("status")).toHaveTextContent("Fleet is cheaper. You save $660 a year.");
    fireEvent.change(slider, { target: { value: "17" } });
    expect(slider).toHaveAttribute("aria-valuetext", "17 people. Studio is cheaper.");
    expect(screen.getByRole("status")).toHaveTextContent("Studio is cheaper. You save $60 a year.");
    expect(screen.getByText("$204")).toBeInTheDocument();
    fireEvent.change(slider, { target: { value: "26" } });
    expect(screen.getByRole("status")).toHaveTextContent("Studio fits up to 25 people, so Fleet it is.");
    expect(screen.getByText("Studio costs less from 17 people. Invites stop at 25, and we never charge for extra people without asking.")).toBeInTheDocument();
  });

  it("compares four plans, including per workspace", () => {
    expect(COMPARE_PLANS).toEqual(["Crew", "Fleet", "Studio", "Mission"]);
    expect(COMPARE.every((row) => row.length === 5)).toBe(true);
    expect(COMPARE[0]).toEqual(["How you pay", "Free", "Per person", "Per workspace", "Yearly agreement"]);
    expect(PLANS.find((p) => p.featured)?.monthly).toBe("$12");
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
