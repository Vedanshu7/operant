import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { IoField } from "@/api/types";

import { InvokeForm } from "./InvokeForm";

const fields: Record<string, IoField> = {
  amount: {
    type: "number",
    description: "Amount",
    required: true,
    sensitive: false,
    data_class: "financial",
  },
  account: {
    type: "string",
    description: "Account",
    required: true,
    sensitive: true,
    data_class: "pii",
  },
  memo: {
    type: "string",
    description: "Memo",
    required: false,
    sensitive: false,
    data_class: "none",
  },
  notify: {
    type: "boolean",
    description: "Notify",
    required: false,
    sensitive: false,
    data_class: "none",
  },
};

describe("InvokeForm", () => {
  it("generates one field per input with the right control type", () => {
    render(<InvokeForm fields={fields} onSubmit={() => undefined} />);
    expect(screen.getByLabelText(/amount/)).toHaveAttribute("type", "number");
    expect(screen.getByLabelText(/account/)).toHaveAttribute("type", "password");
    expect(screen.getByLabelText(/memo/)).toHaveAttribute("type", "text");
    expect(screen.getByLabelText(/notify/)).toHaveAttribute("type", "checkbox");
  });

  it("blocks submit while required fields are empty", async () => {
    const onSubmit = vi.fn();
    render(<InvokeForm fields={fields} onSubmit={onSubmit} />);
    await userEvent.click(screen.getByRole("button", { name: "Invoke" }));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getAllByRole("alert").length).toBeGreaterThanOrEqual(2);
  });

  it("rejects a non-numeric number field", async () => {
    const onSubmit = vi.fn();
    const amountField: IoField = {
      type: "number",
      description: "Amount",
      required: true,
      sensitive: false,
      data_class: "financial",
    };
    render(<InvokeForm fields={{ amount: amountField }} onSubmit={onSubmit} />);
    const amount = screen.getByLabelText<HTMLInputElement>(/amount/);
    amount.type = "text";
    await userEvent.type(amount, "abc");
    await userEvent.click(screen.getByRole("button", { name: "Invoke" }));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(/number/i);
  });

  it("submits a string map", async () => {
    const onSubmit = vi.fn();
    render(<InvokeForm fields={fields} onSubmit={onSubmit} />);
    await userEvent.type(screen.getByLabelText(/amount/), "25");
    await userEvent.type(screen.getByLabelText(/account/), "13344");
    await userEvent.click(screen.getByLabelText(/notify/));
    await userEvent.click(screen.getByRole("button", { name: "Invoke" }));
    expect(onSubmit).toHaveBeenCalledWith({ amount: "25", account: "13344", notify: "true" });
  });
});
