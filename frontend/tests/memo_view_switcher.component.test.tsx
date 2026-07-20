import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { MemoViewSwitcher, type MemoView } from "../components/memo/MemoViewSwitcher";

function SwitcherHarness() {
  const [activeView, setActiveView] = useState<MemoView>("memos");
  return <MemoViewSwitcher activeView={activeView} setActiveView={setActiveView} />;
}

describe("MemoViewSwitcher", () => {
  it("switches between memos and My Context", () => {
    render(<SwitcherHarness />);

    const memosButton = screen.getByRole("button", { name: "メモ" });
    const contextButton = screen.getByRole("button", { name: "マイコンテキスト" });

    expect(memosButton).toHaveAttribute("aria-current", "page");
    expect(contextButton).not.toHaveAttribute("aria-current");

    fireEvent.click(contextButton);

    expect(contextButton).toHaveAttribute("aria-current", "page");
    expect(memosButton).not.toHaveAttribute("aria-current");
  });
});
