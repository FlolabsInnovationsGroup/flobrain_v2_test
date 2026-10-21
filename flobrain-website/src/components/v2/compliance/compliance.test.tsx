import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReviewBoard } from "./ReviewBoard";
import { TrustView } from "./TrustView";
import type { ReviewDetail, ReviewItem, TrustPublic } from "./types";

const get = vi.fn();
const post = vi.fn();
vi.mock("@/lib/v2/api", async (orig) => ({
  ...(await orig<typeof import("@/lib/v2/api")>()),
  api: { get: (...args: unknown[]) => get(...args), post: (...args: unknown[]) => post(...args) },
}));

const item = (id: string, over: Partial<ReviewItem> = {}): ReviewItem => ({
  id,
  subject: { id: `u-${id}`, name: `Person ${id}`, email: `${id}@example.com` },
  kind: "grant",
  label: "Extra permission: audit.view",
  details: { perm_key: "audit.view", expires_at: null },
  reviewer: null,
  decision: "pending",
  change_to: {},
  note: "",
  decided_by: "",
  decided_at: null,
  applied_at: null,
  apply_error: "",
  can_decide: true,
  ...over,
});

const REVIEW: ReviewDetail = {
  id: "r1",
  name: "Access review 2026-Q4",
  period: "2026-Q4",
  reviewer_mode: "team_leads",
  status: "open",
  due_at: null,
  created_at: "2026-10-16T10:00:00Z",
  completed_at: null,
  created_by: "Omar",
  progress: { total: 2, decided: 0, pending: 2, waiting_apply: 0, errors: 0 },
  items: [item("a"), item("b", { kind: "integration", label: "Personal google connection", details: {} })],
  grant_days: [7, 30, 90, 180],
};

describe("access review board", () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    get.mockResolvedValue(REVIEW);
    post.mockImplementation(async (_path: string, body: { decision: string }) => ({ ...item("a"), decision: body.decision, applied_at: "2026-10-21T10:00:00Z" }));
  });

  it("keeps with 1 and confirms a revoke with a second 2", async () => {
    render(<ReviewBoard orgId="o1" reviewId="r1" canView canManage />);
    const list = await screen.findByRole("list", { name: "Access to review" });
    const rows = list.querySelectorAll("li");
    rows[0].focus();
    fireEvent.keyDown(rows[0], { key: "1" });
    await waitFor(() => expect(post).toHaveBeenCalledWith("/orgs/o1/compliance/reviews/r1/items/a/decision", { decision: "keep", change_to: undefined }));

    post.mockClear();
    fireEvent.keyDown(rows[1], { key: "2" });
    expect(post).not.toHaveBeenCalled();
    expect(await screen.findByRole("alert")).toHaveTextContent("removes the access now");
    fireEvent.keyDown(rows[1], { key: "2" });
    await waitFor(() => expect(post).toHaveBeenCalledWith("/orgs/o1/compliance/reviews/r1/items/b/decision", { decision: "revoke", change_to: undefined }));
  });

  it("offers change only where it applies and shows the shortcut help", async () => {
    render(<ReviewBoard orgId="o1" reviewId="r1" canView canManage={false} />);
    await screen.findByText("Person a");
    expect(screen.getAllByRole("button", { name: "Change" })).toHaveLength(1); // the grant, not the connection
    fireEvent.click(screen.getByRole("button", { name: "Keyboard shortcuts" }));
    expect(screen.getByRole("note")).toHaveTextContent("Revoke (press again to confirm)");
    expect(screen.queryByRole("button", { name: "Complete review" })).toBeNull();
  });
});

const PAGE: TrustPublic = {
  org: { name: "Nile Labs" },
  slug: "demo",
  headline: "Security at Nile Labs",
  sections: ["overview", "documents"],
  disclaimer: "x",
  updated_at: "2026-10-19T00:00:00Z",
  overview: "We encrypt everything.",
  documents: [{ key: "dpa", title: "Data processing agreement", description: "" }],
  subprocessors: [{ name: "Hidden Corp", purpose: "", location: "", website: "" }],
};

describe("trust page", () => {
  it("shows only published sections and sends the request", async () => {
    const onRequest = vi.fn().mockResolvedValue(202);
    render(<TrustView data={PAGE} onRequest={onRequest} />);
    expect(screen.getByText("We encrypt everything.")).toBeInTheDocument();
    expect(screen.queryByText("Hidden Corp")).toBeNull();
    expect(screen.getByText(/Readiness, not certification/)).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText(/Data processing agreement/));
    fireEvent.change(screen.getByLabelText("Your name"), { target: { value: "Dana" } });
    fireEvent.change(screen.getByLabelText("Work email"), { target: { value: "dana@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Request documents" }));
    await waitFor(() => expect(onRequest).toHaveBeenCalledWith(expect.objectContaining({ name: "Dana", email: "dana@example.com", documents: ["dpa"], website: "" })));
    expect(await screen.findByText(/The team will check your request/)).toBeInTheDocument();
  });

  it("is inert in the editor preview", () => {
    render(<TrustView data={PAGE} />);
    expect(screen.getByRole("button", { name: "Request documents" })).toBeDisabled();
  });
});
