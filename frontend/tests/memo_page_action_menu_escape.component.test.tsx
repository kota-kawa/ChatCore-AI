// メモ一覧カードの「…」メニューを Escape で閉じ、開いた「…」へフォーカスが戻ることを検証する。
// Tests that Escape closes the memo card "…" menu and returns focus to the "…" that opened it.

import { act, fireEvent, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useMemoPageActionMenu } from "../hooks/memo_page/use_memo_page_action_menu";

function openMenu(memoId: string) {
  const trigger = document.body.appendChild(document.createElement("button"));
  const view = renderHook(() => useMemoPageActionMenu());
  act(() => view.result.current.toggleMemoActionMenu(memoId, trigger));
  return { trigger, ...view };
}

describe("useMemoPageActionMenu Escape", () => {
  it("closes the open menu on Escape and focuses the trigger", () => {
    const { trigger, result } = openMenu("5");
    expect(result.current.openMenuMemoId).toBe("5");

    fireEvent.keyDown(document.body, { key: "Escape" });

    expect(result.current.openMenuMemoId).toBe("");
    expect(result.current.menuPosition).toBeNull();
    expect(trigger).toHaveFocus();
    trigger.remove();
  });

  it("does nothing on Escape while no menu is open", () => {
    const trigger = document.body.appendChild(document.createElement("button"));
    const { result } = renderHook(() => useMemoPageActionMenu());

    fireEvent.keyDown(document.body, { key: "Escape" });

    expect(result.current.openMenuMemoId).toBe("");
    expect(trigger).not.toHaveFocus();
    trigger.remove();
  });
});
