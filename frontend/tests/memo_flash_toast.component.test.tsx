import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MemoFlashToast } from "../components/memo/MemoFlashToast";

describe("MemoFlashToast", () => {
  it("renders nothing without a notice", () => {
    const { container } = render(<MemoFlashToast flash={null} onAction={vi.fn()} />);
    expect(container.firstChild).toBeNull();
  });

  it("announces a success politely and an error as an alert", () => {
    const { rerender } = render(<MemoFlashToast flash={{ type: "success", text: "保存しました" }} onAction={vi.fn()} />);
    expect(screen.getByRole("status").textContent).toBe("保存しました");

    rerender(<MemoFlashToast flash={{ type: "error", text: "失敗しました" }} onAction={vi.fn()} />);
    expect(screen.getByRole("alert").textContent).toBe("失敗しました");
  });

  it("shows the action as a button that calls onAction", () => {
    const onAction = vi.fn();
    render(<MemoFlashToast flash={{ type: "success", text: "移動しました", action: { label: "元に戻す", onAction: vi.fn() } }} onAction={onAction} />);

    fireEvent.click(screen.getByRole("button", { name: "元に戻す" }));

    expect(onAction).toHaveBeenCalledTimes(1);
  });

  it("has no button for a plain notice", () => {
    render(<MemoFlashToast flash={{ type: "success", text: "保存しました" }} onAction={vi.fn()} />);
    expect(screen.queryByRole("button")).toBeNull();
  });
});
