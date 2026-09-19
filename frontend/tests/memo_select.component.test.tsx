import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MemoSelect } from "../components/memo/MemoSelect";
import type { SelectOption } from "../lib/memo/types";

const OPTIONS: SelectOption[] = [
  { value: "a", label: "選択肢A" },
  { value: "b", label: "選択肢B" },
  { value: "c", label: "選択肢C" },
];

function renderSelect(overrides: Partial<Parameters<typeof MemoSelect>[0]> = {}) {
  const onChange = overrides.onChange ?? vi.fn();
  render(
    <MemoSelect
      value="a"
      onChange={onChange}
      options={OPTIONS}
      ariaLabel="並び順"
      {...overrides}
    />,
  );
  return { onChange, trigger: screen.getByRole("button", { name: "並び順" }) };
}

// カスタムセレクトはマウス専用UIになりがちなので、矢印キー・Enter・Escape・Home/Endの
// キーボード操作だけで選択・閉じる操作が完結することを固定する。
// Custom selects easily become mouse-only UI, so lock in that arrow keys, Enter, Escape,
// and Home/End alone are enough to choose an option and close the menu.
describe("MemoSelect keyboard access", () => {
  it("opens with ArrowDown on the trigger and exposes a listbox", () => {
    const { trigger } = renderSelect();

    fireEvent.keyDown(trigger, { key: "ArrowDown" });

    const listbox = screen.getByRole("listbox");
    expect(listbox).toBeInTheDocument();
    expect(trigger).toHaveAttribute("aria-expanded", "true");
  });

  it("moves the active descendant with ArrowDown/ArrowUp and wraps at the edges", () => {
    renderSelect();
    fireEvent.click(screen.getByRole("button", { name: "並び順" }));
    const listbox = screen.getByRole("listbox");
    const options = screen.getAllByRole("option");

    // 開いた直後は現在の選択値（先頭のA）がアクティブ候補
    // Right after opening, the current value (A) is the active candidate
    expect(listbox).toHaveAttribute("aria-activedescendant", options[0].id);

    fireEvent.keyDown(listbox, { key: "ArrowDown" });
    expect(listbox).toHaveAttribute("aria-activedescendant", options[1].id);

    fireEvent.keyDown(listbox, { key: "ArrowUp" });
    fireEvent.keyDown(listbox, { key: "ArrowUp" });
    expect(listbox).toHaveAttribute("aria-activedescendant", options[2].id);
  });

  it("jumps to the first/last option with Home/End", () => {
    renderSelect();
    fireEvent.click(screen.getByRole("button", { name: "並び順" }));
    const listbox = screen.getByRole("listbox");
    const options = screen.getAllByRole("option");

    fireEvent.keyDown(listbox, { key: "End" });
    expect(listbox).toHaveAttribute("aria-activedescendant", options[2].id);

    fireEvent.keyDown(listbox, { key: "Home" });
    expect(listbox).toHaveAttribute("aria-activedescendant", options[0].id);
  });

  it("commits the active option with Enter and returns focus to the trigger", async () => {
    const { onChange, trigger } = renderSelect();
    fireEvent.click(trigger);
    const listbox = screen.getByRole("listbox");

    fireEvent.keyDown(listbox, { key: "ArrowDown" });
    fireEvent.keyDown(listbox, { key: "Enter" });

    expect(onChange).toHaveBeenCalledWith("b");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    await vi.waitFor(() => expect(trigger).toHaveFocus());
  });

  it("closes without changing the value on Escape and returns focus to the trigger", async () => {
    const { onChange, trigger } = renderSelect();
    fireEvent.click(trigger);
    const listbox = screen.getByRole("listbox");

    fireEvent.keyDown(listbox, { key: "ArrowDown" });
    fireEvent.keyDown(listbox, { key: "Escape" });

    expect(onChange).not.toHaveBeenCalled();
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    await vi.waitFor(() => expect(trigger).toHaveFocus());
  });
});
