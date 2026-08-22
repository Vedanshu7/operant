import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import type { DiscoveryRequest, ReplayRequest } from "@/api/types";
import { runFixtures } from "@/mocks/fixtures";
import { server } from "@/mocks/server";
import { renderWithProviders } from "@/test/render";

import { GoalForm } from "./GoalForm";

describe("GoalForm", () => {
  it("discover mode posts goal, profile and inputs to /runs/discovery", async () => {
    const bodies: DiscoveryRequest[] = [];
    server.use(
      http.post("/api/v1/runs/discovery", async ({ request }) => {
        bodies.push((await request.json()) as DiscoveryRequest);
        return HttpResponse.json(runFixtures[0]);
      }),
    );
    renderWithProviders(<GoalForm />);
    await userEvent.type(screen.getByLabelText("Goal"), "Transfer $25 to savings");
    await screen.findByRole("option", { name: /ParaBank/ });
    await userEvent.selectOptions(screen.getByLabelText("Profile"), "parabank");
    await userEvent.selectOptions(screen.getByLabelText("Tenant"), "demo");
    await userEvent.click(screen.getByRole("button", { name: "+ Add input" }));
    await userEvent.type(screen.getByLabelText("Input 1 key"), "amount");
    await userEvent.type(screen.getByLabelText("Input 1 value"), "25");
    await userEvent.click(screen.getByRole("button", { name: "Start discovery" }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({
      goal: "Transfer $25 to savings",
      capability_id: "transfer-25-to-savings",
      profile_id: "parabank",
      tenant: "demo",
      inputs: { amount: "25" },
      screenshots: true,
      capture: false,
    });
  });

  it("bootstrap profile sends profile_id null", async () => {
    const bodies: DiscoveryRequest[] = [];
    server.use(
      http.post("/api/v1/runs/discovery", async ({ request }) => {
        bodies.push((await request.json()) as DiscoveryRequest);
        return HttpResponse.json(runFixtures[0]);
      }),
    );
    renderWithProviders(<GoalForm />);
    await userEvent.type(screen.getByLabelText("Goal"), "Find the Wi-Fi name");
    await userEvent.click(screen.getByRole("button", { name: "Start discovery" }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]?.profile_id).toBeNull();
  });

  it("replay mode posts capability inputs to /runs/replay", async () => {
    const bodies: ReplayRequest[] = [];
    server.use(
      http.post("/api/v1/runs/replay", async ({ request }) => {
        bodies.push((await request.json()) as ReplayRequest);
        return HttpResponse.json(runFixtures[1]);
      }),
    );
    renderWithProviders(<GoalForm />);
    await userEvent.click(screen.getByRole("tab", { name: "replay" }));
    await screen.findByRole("option", { name: /Transfer funds/ });
    await userEvent.selectOptions(screen.getByLabelText("Capability"), "parabank.transfer");
    await userEvent.type(await screen.findByLabelText(/amount/), "25");
    await userEvent.type(screen.getByLabelText(/from_account/), "13344");
    await userEvent.type(screen.getByLabelText(/to_account/), "13455");
    await userEvent.click(screen.getByLabelText(/Fresh session/));
    await userEvent.click(screen.getByRole("button", { name: "Start replay" }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toEqual({
      capability_id: "parabank.transfer",
      inputs: { amount: "25", from_account: "13344", to_account: "13455", confirm_email: "false" },
      fresh_session: true,
    });
  });
});
