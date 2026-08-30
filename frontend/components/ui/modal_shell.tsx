import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { useModalFocusTrap } from "../../hooks/use_modal_focus_trap";

// 中央寄せモーダル（`.modal-base`）共通の外殻。
// - `document.body` へポータルするため、`perspective` などで包含ブロックが
//   作られた領域の内側から使っても、オーバーレイが画面全体を覆う。
// - role/aria、`is-open` トグル、フォーカストラップ、背景クリック / Escape の
//   閉じる操作をここへ集約し、各モーダルは中身だけを渡す。
// Shared shell for centered `.modal-base` modals.
// - Portals to `document.body`, so the overlay always covers the full viewport
//   even when the modal is used from inside a containing block (e.g. `perspective`).
// - Centralizes role/aria, the `is-open` toggle, the focus trap, and the
//   backdrop-click / Escape close handling; each modal only supplies its body.
type ModalShellProps = {
  // モーダルの開閉状態 / Whether the modal is open
  isOpen: boolean;
  // 閉じる要求（背景クリック・Escape から呼ばれる） / Close request (backdrop click / Escape)
  onClose: () => void;
  // タイトル要素の id（aria-labelledby） / Id of the title element (aria-labelledby)
  labelledBy: string;
  // オーバーレイ要素に付与する追加クラス / Extra classes for the overlay element
  className?: string;
  // オーバーレイ要素の id（既存の DOM/CSS/テスト互換のため） / Overlay element id (for existing DOM/CSS/test compatibility)
  id?: string;
  // 送信中などに背景クリック・Escape での閉じるを無効化する / Block backdrop / Escape close while e.g. submitting
  dismissDisabled?: boolean;
  // 初期フォーカス要素を返す。省略時はオーバーレイ内の最初のフォーカス可能要素 / Returns the initial focus target (defaults to the first focusable element)
  getInitialFocus?: () => HTMLElement | null;
  // getInitialFocus の簡易版。オーバーレイ内をこのセレクタで検索する / Simple form of getInitialFocus: query the overlay with this selector
  initialFocusSelector?: string;
  children: ReactNode;
};

export function ModalShell({
  isOpen,
  onClose,
  labelledBy,
  className,
  id,
  dismissDisabled = false,
  getInitialFocus,
  initialFocusSelector,
  children,
}: ModalShellProps) {
  const overlayRef = useRef<HTMLDivElement | null>(null);

  // SSR ではポータル先が無いため、マウント後にのみ描画する。
  // No portal target during SSR, so only render after mount.
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    setMounted(true);
  }, []);

  const resolveInitialFocus = useCallback(() => {
    if (getInitialFocus) return getInitialFocus();
    if (initialFocusSelector) {
      return overlayRef.current?.querySelector<HTMLElement>(initialFocusSelector) ?? null;
    }
    return null;
  }, [getInitialFocus, initialFocusSelector]);

  const handleEscape = useCallback(() => {
    if (dismissDisabled) return;
    onClose();
  }, [dismissDisabled, onClose]);

  useModalFocusTrap({
    isOpen,
    containerRef: overlayRef,
    getInitialFocus: resolveInitialFocus,
    onEscape: handleEscape,
  });

  if (!mounted) return null;

  return createPortal(
    <div
      ref={overlayRef}
      id={id}
      className={`${className ? `${className} ` : ""}modal-base${isOpen ? " is-open" : ""}`}
      role="dialog"
      aria-modal="true"
      aria-hidden={isOpen ? "false" : "true"}
      aria-labelledby={labelledBy}
      tabIndex={-1}
      // 背景（オーバーレイ自身）をクリックしたときだけ閉じる
      // Close only when the backdrop (the overlay itself) is clicked
      onClick={(event) => {
        if (event.target === event.currentTarget && !dismissDisabled) {
          onClose();
        }
      }}
    >
      {children}
    </div>,
    document.body,
  );
}
