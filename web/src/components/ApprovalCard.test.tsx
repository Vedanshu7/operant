import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import type { Approval, ApprovalDecision } from "@/api/types";
import { approvalFixture, scopeApprovalFixture } from "@/mocks/fixtures";
import { server } from "@/mocks/server";
import { renderWithProviders } from "@/test/render";

import { ApprovalCard } from "./ApprovalCard";

function captureDecision(): { bodies: ApprovalDecision[] } {
  const bodies: ApprovalDecision[] = [];
  server.use(
    http.post("/api/v1/approvals/:id", async ({ request }) => {
      const body = (await request.json()) as ApprovalDecision;
      bodies.push(body);
      const decided: Approval = {
        ...approvalFixture,
        status: body.approved ? "approved" : "denied",
      };
      return HttpResponse.json(decided);
    }),
  );
  return { bodies };
}

describe("ApprovalCard", () => {
  it("renders the kind badge, summary and details", () => {
    renderWithProviders(<ApprovalCard approval={approvalFixture} />);
    expect(screen.getByText("mutating")).toBeInTheDocument();
    expect(screen.getByText(approvalFixture.summary)).toBeInTheDocument();
    expect(screen.getByText("from_account")).toBeInTheDocument();
    expect(screen.getByText("13344")).toBeInTheDocument();
  });

  it("renders proposed grants for scope approvals", () => {
    renderWithProviders(<ApprovalCard approval={scopeApprovalFixture} />);
    expect(screen.getByText("scope")).toBeInTheDocument();
    expect(screen.getByText("com.apple.systempreferences")).toBeInTheDocument();
  });

  it("Approve once posts approved:true remember:once", async () => {
    const { bodies } = captureDecision();
    renderWithProviders(<ApprovalCard approval={approvalFixture} />);
    await userEvent.click(screen.getByRole("button", { name: "Approve once" }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toEqual({ approved: true, remember: "once" });
  });

  it("Approve for this run posts remember:process", async () => {
    const { bodies } = captureDecision();
    renderWithProviders(<ApprovalCard approval={approvalFixture} />);
    await userEvent.click(screen.getByRole("button", { name: "Approve for this run" }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ approved: true, remember: "process" });
  });

  it("Deny posts approved:false with the note", async () => {
    const { bodies } = captureDecision();
    renderWithProviders(<ApprovalCard approval={approvalFixture} />);
    await userEvent.type(screen.getByLabelText(/Note/), "not now");
    await userEvent.click(screen.getByRole("button", { name: "Deny" }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toEqual({ approved: false, remember: "once", note: "not now" });
  });

  it("requires a note before denying a sensitive_export", async () => {
    const { bodies } = captureDecision();
    const approval: Approval = { ...approvalFixture, kind: "sensitive_export" };
    renderWithProviders(<ApprovalCard approval={approval} />);
    await userEvent.click(screen.getByRole("button", { name: "Deny" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/note is required/i);
    expect(bodies).toHaveLength(0);
    await userEvent.type(screen.getByLabelText(/Note/), "export not allowed");
    await userEvent.click(screen.getByRole("button", { name: "Deny" }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toEqual({ approved: false, remember: "once", note: "export not allowed" });
  });
});
