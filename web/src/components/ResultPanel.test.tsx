import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import type { RunDetail } from "@/api/types";

import { ResultPanel } from "./ResultPanel";

describe("ResultPanel", () => {
  it("warns when a successful run saw a changed screen", () => {
    const run = {
      id: "r1",
      kind: "replay",
      status: "succeeded",
      result: { status: "success", outputs: {}, drifted: ["accounts"] },
    } as unknown as RunDetail;
    render(
      <MemoryRouter>
        <ResultPanel run={run} />
      </MemoryRouter>,
    );
    expect(screen.getByText(/no longer look as recorded: accounts/)).toBeInTheDocument();
  });
});
