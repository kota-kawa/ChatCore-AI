import { useCallback, useEffect, useState } from "react";

import type { MemoActionMenuPosition } from "../../lib/memo/types";
import { getMemoActionMenuPosition } from "../../lib/memo/utils";

// メモカードのアクションメニュー（開いているメモ・表示位置・外側クリックで閉じる）
// The per-memo action dropdown (which memo is open, where it renders, outside-click dismissal)
export function useMemoPageActionMenu() {
  // Memo item dropdown menu
  const [openMenuMemoId, setOpenMenuMemoId] = useState<string>("");
  const [menuPosition, setMenuPosition] = useState<MemoActionMenuPosition | null>(null);

  // メモアクションメニュー外のクリックやスクロールでメニューを閉じる副作用
  // Effect to close the memo action menu on outside click or scroll
  useEffect(() => {
    if (!openMenuMemoId) return;
    const onDown = (e: MouseEvent) => {
      const target = e.target as Element;
      if (!target.closest?.(".memo-item__menu-wrap") && !target.closest?.(".memo-item__dropdown")) {
        setOpenMenuMemoId("");
        setMenuPosition(null);
      }
    };
    const onScrollOrResize = () => {
      setOpenMenuMemoId("");
      setMenuPosition(null);
    };
    document.addEventListener("mousedown", onDown);
    window.addEventListener("scroll", onScrollOrResize, true);
    window.addEventListener("resize", onScrollOrResize);
    return () => {
      document.removeEventListener("mousedown", onDown);
      window.removeEventListener("scroll", onScrollOrResize, true);
      window.removeEventListener("resize", onScrollOrResize);
    };
  }, [openMenuMemoId]);

  const closeMemoActionMenu = useCallback(() => {
    setOpenMenuMemoId("");
    setMenuPosition(null);
  }, []);

  const toggleMemoActionMenu = useCallback((memoId: string, trigger: HTMLElement) => {
    if (openMenuMemoId === memoId) {
      setOpenMenuMemoId("");
      setMenuPosition(null);
      return;
    }
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
