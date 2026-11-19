// 自動保存された記憶の通知の表示（記憶しました・取り消す・リンク）と、取り消し中の二重送信防止、取り消し後の表示を検証する。
// Tests the auto-saved memory notices: the saved row, undo, the memory link, double-press protection and the undone row.

import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AutoSavedMemoryNotices } from "../components/chat_page/auto_saved_memory_notices";
import { LocaleProvider } from "../contexts/locale_context";
import type { AutoSavedMemoryEntry } from "../lib/chat_page/auto_saved_memory_state";

const entry = (overrides: Partial<AutoSavedMemoryEntry> = {}): AutoSavedMemoryEntry => ({
  id: 31,
  messageId: 55,
  title: "Rust でコンパイラを書いている",
  revision: 2,
  status: "saved",
  ...overrides,
});

describe("AutoSavedMemoryNotices", () => {
  it("shows the saved title, an undo button and a link that opens the memory view", () => {
    render(<AutoSavedMemoryNotices entries={[entry(), entry({ id: 32, title: "二件目" })]} onUndo={vi.fn()} />);

    expect(screen.getByRole("list", { name: "自動で保存した記憶" })).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByText("Rust でコンパイラを書いている")).toBeInTheDocument();
    expect(screen.getAllByText("記憶しました：")).toHaveLength(2);
    expect(screen.getAllByRole("link", { name: /記憶を開く/ })[0]).toHaveAttribute("href", "/memo?view=context");
    expect(screen.getByRole("button", { name: "「Rust でコンパイラを書いている」の記憶を取り消す" })).toHaveTextContent("取り消す");
  });

  it("sends the notice to onUndo once while the undo is in flight", async () => {
    let finishUndo: () => void = () => undefined;
    const onUndo = vi.fn(() => new Promise<void>((resolve) => { finishUndo = resolve; }));
    render(<AutoSavedMemoryNotices entries={[entry()]} onUndo={onUndo} />);

    const button = screen.getByRole("button", { name: /取り消す/ });
    fireEvent.click(button);
    fireEvent.click(button);
    expect(onUndo).toHaveBeenCalledTimes(1);
    expect(onUndo).toHaveBeenCalledWith(expect.objectContaining({ id: 31, revision: 2 }));
    expect(button).toBeDisabled();

    await act(async () => finishUndo());
    expect(button).toBeEnabled();
  });

  it("turns into an undone row without the undo button or the link", () => {
    render(<AutoSavedMemoryNotices entries={[entry({ status: "undone" })]} onUndo={vi.fn()} />);

    expect(screen.getByText("取り消しました")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.queryByText("Rust でコンパイラを書いている")).not.toBeInTheDocument();
  });

  it("renders nothing without entries and uses English text in the English UI", () => {
    const { container, rerender } = render(<AutoSavedMemoryNotices entries={[]} onUndo={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();

    rerender(
      <LocaleProvider initialLocale="en">
        <AutoSavedMemoryNotices entries={[entry({ title: "Writes a compiler in Rust" })]} onUndo={vi.fn()} />
      </LocaleProvider>,
    );
    expect(screen.getByText("Remembered:")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Undo remembering “Writes a compiler in Rust”" })).toHaveTextContent("Undo");
    expect(screen.getByRole("link", { name: /Open memory/ })).toBeInTheDocument();
  });
});
