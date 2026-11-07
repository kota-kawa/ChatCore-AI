// メモカードのアクションメニュー（開閉状態と表示位置）を管理するフック。
// Hook managing the memo card action menu (open state and position).
import { useCallback, useEffect, useRef, useState } from "react";

import type { MemoActionMenuPosition } from "../../lib/memo/types";
import { getMemoActionMenuPosition } from "../../lib/memo/utils";
import { useDismissOnEscape } from "../use_dismiss_on_escape";
import { useDismissOnOutsidePress } from "../use_dismiss_on_outside_press";

// メモカードのアクションメニュー（開いているメモ・表示位置・外側の押下で閉じる）
// The per-memo action dropdown (which memo is open, where it renders, outside-press dismissal)
export function useMemoPageActionMenu() {
  // メモカードのドロップダウンメニューの状態。
  // Memo item dropdown menu
  const [openMenuMemoId, setOpenMenuMemoId] = useState<string>("");
  const [menuPosition, setMenuPosition] = useState<MemoActionMenuPosition | null>(null);

  // 開いているメニューの「…」ボタン。ほかのカードの「…」は外側として扱う
  // The "…" button of the open menu; another card's "…" counts as outside
  const openTriggerRef = useRef<HTMLElement | null>(null);

  const closeMemoActionMenu = useCallback(() => {
    setOpenMenuMemoId("");
    setMenuPosition(null);
  }, []);

  // 外側の押下はメニューを閉じるだけにする。メニュー本体は body へポータルされ、同時に 1 つしか開かない
  // A press outside only closes the menu; the menu is portaled to body and only one is open at a time
  useDismissOnOutsidePress(
    Boolean(openMenuMemoId),
    (target) => Boolean(
      openTriggerRef.current?.contains(target) || (target instanceof Element && target.closest(".memo-item__dropdown")),
    ),
    closeMemoActionMenu,
  );
  // Escape でも閉じて開いた「…」へフォーカスを戻す / Escape closes it too and returns focus to the "…" that opened it
  useDismissOnEscape(Boolean(openMenuMemoId), closeMemoActionMenu, openTriggerRef);

  // スクロールやリサイズで位置がずれるので閉じる / Close on scroll or resize, which would misplace the menu
  useEffect(() => {
    if (!openMenuMemoId) return;
    window.addEventListener("scroll", closeMemoActionMenu, true);
    window.addEventListener("resize", closeMemoActionMenu);
    return () => {
      window.removeEventListener("scroll", closeMemoActionMenu, true);
      window.removeEventListener("resize", closeMemoActionMenu);
    };
  }, [closeMemoActionMenu, openMenuMemoId]);

  const toggleMemoActionMenu = useCallback((memoId: string, trigger: HTMLElement) => {
    if (openMenuMemoId === memoId) {
      setOpenMenuMemoId("");
      setMenuPosition(null);
      return;
    }
    openTriggerRef.current = trigger;
    setMenuPosition(getMemoActionMenuPosition(trigger));
    setOpenMenuMemoId(memoId);
  }, [openMenuMemoId]);

  return {
    openMenuMemoId,
    setOpenMenuMemoId,
    menuPosition,
    setMenuPosition,
    closeMemoActionMenu,
    toggleMemoActionMenu,
  };
}
