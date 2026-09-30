import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router";
import { beforeEach, describe, expect, it } from "vitest";

import type { CapabilityDetail } from "@/api/types";
import { state } from "@/mocks/handlers";
import { renderWithProviders } from "@/test/render";

import { CapabilityPage } from "./CapabilityPage";

function showPage(id: string): void {
  renderWithProviders(
    <Routes>
      <Route path="/capabilities/:id" element={<CapabilityPage />} />
    </Routes>,
    { route: `/capabilities/${id}` },
  );
}

function capability(): CapabilityDetail {
  const cap = state.capabilities[0];
  if (!cap) throw new Error("no capability fixture");
  return cap;
}

describe("CapabilityPage", () => {
  beforeEach(() => {
    const cap = capability();
    cap.status = "draft";
    cap.gate = { ...cap.gate, passes: true };
    cap.graph_version = 2;
    cap.latest_graph_version = 2;
    cap.unknown_steps = [
      { edge: "e1", description: "open reports", judged: "unsure", reviewed: false },
    ];
  });

  it("shows the steps an approval reviews", async () => {
    showPage(capability().id);
    expect(await screen.findByText(/open reports/)).toBeInTheDocument();
    expect(screen.getByText(/judge: unsure/)).toBeInTheDocument();
  });

  it("sends the steps it showed", async () => {
    showPage(capability().id);
    await userEvent.click(await screen.findByRole("button", { name: "Approve" }));
    await waitFor(() => expect(capability().status).toBe("approved"));
  });

  it("offers a move only when a newer graph exists", async () => {
    showPage(capability().id);
    await screen.findByRole("button", { name: "Rediscover" });
    expect(screen.queryByRole("button", { name: /Move to graph/ })).not.toBeInTheDocument();
  });

  it("moves to a newer graph", async () => {
    capability().latest_graph_version = 3;
    showPage(capability().id);
    await userEvent.click(await screen.findByRole("button", { name: "Move to graph v3" }));
    await waitFor(() => expect(capability().graph_version).toBe(3));
  });
});
