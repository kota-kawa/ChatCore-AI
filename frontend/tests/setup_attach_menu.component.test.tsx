import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SetupAttachMenu } from "../components/chat_page/setup_attach_menu";

function renderMenu(overrides: Partial<Parameters<typeof SetupAttachMenu>[0]> = {}) {
  const onSelectFile = vi.fn();
  const onToggleMemoLookup = vi.fn();
  const onToggleSharedPromptLookup = vi.fn();
  render(
    <SetupAttachMenu
      disabled={false}
      fileItemDisabled={false}
      memoLookupEnabled={false}
      memoItemDisabled={false}
      sharedPromptLookupEnabled={false}
      onToggleMemoLookup={onToggleMemoLookup}
      onToggleSharedPromptLookup={onToggleSharedPromptLookup}
      onSelectFile={onSelectFile}
      {...overrides}
    />,
  );
  return {
    onSelectFile,
    onToggleMemoLookup,
    onToggleSharedPromptLookup,
    trigger: screen.getByRole("button", { name: "追加メニューを開く" }),
  };
}

describe("SetupAttachMenu", () => {
  // クリップを押した時点でファイル選択が開いてしまうと、メモや共有プロンプトを選べない。
  // Opening the file picker on the paperclip click would leave no room for the other entries.
  it("shows the three entries instead of opening the file picker", () => {
    const { onSelectFile, trigger } = renderMenu();

    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("menu", { hidden: true })).toHaveAttribute("aria-hidden", "true");

    fireEvent.click(trigger);

    expect(trigger).toHaveAttribute("aria-expanded", "true");
    const menu = screen.getByRole("menu");
    expect(menu).toHaveAttribute("aria-hidden", "false");
    expect(menu).toHaveClass("is-open");
    expect(
      [...screen.getAllByRole("menuitemcheckbox"), ...screen.getAllByRole("menuitem")].map(
        (item) => item.textContent,
      ),
    ).toEqual(["メモ", "共有プロンプト", "ファイル添付"]);
    expect(onSelectFile).not.toHaveBeenCalled();
  });

  it("opens the file picker only from the file entry, then closes the menu", () => {
    const { onSelectFile, trigger } = renderMenu();

    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole("menuitem", { name: "ファイル添付" }));

    expect(onSelectFile).toHaveBeenCalledTimes(1);
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  it("closes on outside clicks and on Escape", () => {
    const { trigger } = renderMenu();

    fireEvent.click(trigger);
    fireEvent.pointerDown(document.body);
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(trigger);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  // 添付上限に達しても、メモと共有プロンプトは選べる必要がある。
  // Hitting the attachment limit must not lock the memo and shared prompt entries.
  it("disables only the file entry when the attachment limit is reached", () => {
    const { trigger } = renderMenu({ fileItemDisabled: true });

    fireEvent.click(trigger);

    expect(screen.getByRole("menuitem", { name: "ファイル添付" })).toBeDisabled();
    expect(screen.getByRole("menuitemcheckbox", { name: "メモ" })).toBeEnabled();
  });

  // メモはトグル。押すと参照モードが切り替わり、状態はチェック済みとして読み上げられる。
  // Memo is a toggle: clicking it flips the lookup mode, and the state is exposed as checked.
  it("toggles the memo lookup mode and reports its state", () => {
    const { onToggleMemoLookup, trigger } = renderMenu();

    fireEvent.click(trigger);
    const memoItem = screen.getByRole("menuitemcheckbox", { name: "メモ" });
    expect(memoItem).toHaveAttribute("aria-checked", "false");

    fireEvent.click(memoItem);

    expect(onToggleMemoLookup).toHaveBeenCalledTimes(1);
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  it("marks the memo entry as checked while the lookup mode is on", () => {
    const { trigger } = renderMenu({ memoLookupEnabled: true });

    fireEvent.click(trigger);

    expect(screen.getByRole("menuitemcheckbox", { name: "メモ" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });

  // 共有プロンプトは公開データなので、未ログインでもトグルできる必要がある。
  // Shared prompts are public, so the toggle must stay usable when signed out.
  it("toggles the shared prompt lookup and stays available when logged out", () => {
    const { onToggleSharedPromptLookup, trigger } = renderMenu({ memoItemDisabled: true });

    fireEvent.click(trigger);
    const sharedPromptItem = screen.getByRole("menuitemcheckbox", { name: "共有プロンプト" });

    expect(sharedPromptItem).toBeEnabled();
    expect(sharedPromptItem).toHaveAttribute("aria-checked", "false");

    fireEvent.click(sharedPromptItem);

    expect(onToggleSharedPromptLookup).toHaveBeenCalledTimes(1);
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  it("marks the shared prompt entry as checked while its lookup is on", () => {
    const { trigger } = renderMenu({ sharedPromptLookupEnabled: true });

    fireEvent.click(trigger);

    expect(screen.getByRole("menuitemcheckbox", { name: "共有プロンプト" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });

  // 自分のメモはログイン中しか読めないので、未ログインでは選べないようにする。
  // Memos are owner-only, so the entry must be unavailable when signed out.
  it("disables the memo entry when the user is logged out", () => {
    const { onToggleMemoLookup, trigger } = renderMenu({ memoItemDisabled: true });

    fireEvent.click(trigger);
    const memoItem = screen.getByRole("menuitemcheckbox", { name: "メモ" });

    expect(memoItem).toBeDisabled();
    fireEvent.click(memoItem);
    expect(onToggleMemoLookup).not.toHaveBeenCalled();
  });
});
