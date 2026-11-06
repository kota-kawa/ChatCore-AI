// 中央寄せモーダルの共通の外殻。document.body へのポータル、ARIA 属性、フォーカストラップ、背景クリック・Escape での閉じる操作をまとめる。
// Common shell for centered modals: body portal, ARIA attributes, focus trap, and backdrop-click / Escape closing.
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type MutableRefObject,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";

import { useModalFocusTrap } from "../../hooks/use_modal_focus_trap";
import { computeModalReturnMotion, findModalOrigin, type ModalReturnMotion } from "../../lib/ui/modal_return_target";

// 閉じる動きの長さ。modal_surface.css の --cc-modal-exit-duration と同じ値にする。
// Length of the closing motion; keep equal to --cc-modal-exit-duration in modal_surface.css.
export const MODAL_EXIT_DURATION_MS = 200;

// 中央寄せモーダル（`.modal-base`）共通の外殻。
// - `document.body` へポータルするため、`perspective` などで包含ブロックが
//   作られた領域の内側から使っても、オーバーレイが画面全体を覆う。
// - role/aria、`is-open` トグル、フォーカストラップ、背景クリック / Escape の
//   閉じる操作をここへ集約し、各モーダルは中身だけを渡す。
// - 閉じた直後の MODAL_EXIT_DURATION_MS の間は `is-closing` を付け、開いていたときの中身を
//   残したまま薄れさせる（`returnTo` があれば元のカードへ縮んで戻る）。呼び出し元が閉じると
//   同時にデータを消しても、消える途中の面が空にならない。
// Shared shell for centered `.modal-base` modals.
// - Portals to `document.body`, so the overlay always covers the full viewport
//   even when the modal is used from inside a containing block (e.g. `perspective`).
// - Centralizes role/aria, the `is-open` toggle, the focus trap, and the
//   backdrop-click / Escape close handling; each modal only supplies its body.
// - For MODAL_EXIT_DURATION_MS after closing it carries `is-closing` and keeps the content it
//   showed while open, so it fades out (or shrinks back into its card when `returnTo` is set)
//   even when the caller clears its data at the moment it closes.
type ModalShellProps = {
  // モーダルの開閉状態 / Whether the modal is open
  isOpen: boolean;
  // 閉じる要求（背景クリック・Escape から呼ばれる） / Close request (backdrop click / Escape)
  onClose: () => void;
  // タイトル要素の id（aria-labelledby） / Id of the title element (aria-labelledby)
  labelledBy: string;
  // オーバーレイ要素に付与する追加クラス / Extra classes for the overlay element
  className?: string;
  style?: CSSProperties;
  // オーバーレイ要素の id（既存の DOM/CSS/テスト互換のため） / Overlay element id (for existing DOM/CSS/test compatibility)
  id?: string;
  // 送信中などに背景クリック・Escape での閉じるを無効化する / Block backdrop / Escape close while e.g. submitting
  dismissDisabled?: boolean;
  // 初期フォーカス要素を返す。省略時はオーバーレイ内の最初のフォーカス可能要素 / Returns the initial focus target (defaults to the first focusable element)
  getInitialFocus?: () => HTMLElement | null;
  // getInitialFocus の簡易版。オーバーレイ内をこのセレクタで検索する / Simple form of getInitialFocus: query the overlay with this selector
  initialFocusSelector?: string;
  // オーバーレイ要素を外から参照したい呼び出し元向け（スクロールロック等の既存管理と併用する）
  // For callers that need the overlay element (e.g. to coordinate an existing scroll-lock manager)
  overlayRef?: MutableRefObject<HTMLDivElement | null>;
  // 開いた元のカードの目印（lib/ui/modal_return_target の modalOriginKey）。閉じるとき、そのカードが
  // 画面に見えていればそこへ縮んで戻る。開いていた間の最後の値を使う
  // Marker of the card this modal was opened from (modalOriginKey in lib/ui/modal_return_target).
  // On close the panel shrinks back into that card when it is visible; the last value seen while open is used
  returnTo?: string | null;
  children: ReactNode;
};

function returnMotionStyle(motion: ModalReturnMotion): CSSProperties {
  return {
    "--cc-modal-return-x": `${motion.x}px`,
    "--cc-modal-return-y": `${motion.y}px`,
    "--cc-modal-return-scale-x": String(motion.scaleX),
    "--cc-modal-return-scale-y": String(motion.scaleY),
  } as CSSProperties;
}

// dismissDisabled の間は、背景クリックと Escape のどちらでも閉じない（送信中などに誤って閉じないため）
// While dismissDisabled is set, neither backdrop click nor Escape closes the modal (e.g. to avoid closing mid-submit)
export function ModalShell({
  isOpen,
  onClose,
  labelledBy,
  className,
  style,
  id,
  dismissDisabled = false,
  getInitialFocus,
  initialFocusSelector,
  overlayRef: externalOverlayRef,
  returnTo,
  children,
}: ModalShellProps) {
  const overlayRef = useRef<HTMLDivElement | null>(null);
  // 内部 ref と外部 ref の両方に同じ要素を渡す / Feed the same element to the internal and external refs
  const setOverlayRef = useCallback(
    (element: HTMLDivElement | null) => {
      overlayRef.current = element;
      if (externalOverlayRef) externalOverlayRef.current = element;
    },
    [externalOverlayRef],
  );

  // SSR ではポータル先が無いため、マウント後にのみ描画する。
  // No portal target during SSR, so only render after mount.
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    setMounted(true);
  }, []);

  // 開いた → 閉じたに変わったレンダーで閉じる途中に入る（前回の値と比べて描画中に state を合わせる）
  // Enter the closing phase on the render where isOpen turns false (state adjusted during render against the previous value)
  const [previousIsOpen, setPreviousIsOpen] = useState(isOpen);
  const [isClosing, setIsClosing] = useState(false);
  if (previousIsOpen !== isOpen) {
    setPreviousIsOpen(isOpen);
    setIsClosing(!isOpen);
  }

  // 開いていた間に最後に描いた中身と戻り先。閉じる途中はこれを描き続ける
  // The content and return target last rendered while open; the closing phase keeps drawing them
  const openContentRef = useRef<ReactNode>(null);
  const openReturnToRef = useRef<string | null>(null);
  useLayoutEffect(() => {
    if (!isOpen) return;
    openContentRef.current = children;
    openReturnToRef.current = returnTo ?? null;
  });

  // 閉じる途中に入ったら、戻り先のカードが見えていればパネルからの移動量を測り、動きの長さだけ待って終える。
  // 描画前に測るので、縮み始めの位置が 1 フレームずれることはない
  // On entering the closing phase, measure the move from the panel to its card (when visible) and end after
  // the motion's length. Measuring before paint keeps the first frame of the shrink in place
  const [returnMotion, setReturnMotion] = useState<ModalReturnMotion | null>(null);
  useLayoutEffect(() => {
    if (!isClosing) return;
    const returnKey = openReturnToRef.current;
    const panel = overlayRef.current?.querySelector<HTMLElement>(".cc-modal__panel");
    const target = returnKey ? findModalOrigin(returnKey) : null;
    setReturnMotion(
      panel && target ? computeModalReturnMotion(panel.getBoundingClientRect(), target.getBoundingClientRect()) : null,
    );
    const timer = window.setTimeout(() => {
      openContentRef.current = null;
      setIsClosing(false);
      setReturnMotion(null);
    }, MODAL_EXIT_DURATION_MS);
    return () => window.clearTimeout(timer);
  }, [isClosing]);

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

  const isReturning = isClosing && returnMotion !== null;
  const overlayStyle = isReturning ? { ...style, ...returnMotionStyle(returnMotion) } : style;

  return createPortal(
    <div
      ref={setOverlayRef}
      id={id}
      className={`${className ? `${className} ` : ""}modal-base${isOpen ? " is-open" : ""}${isClosing ? " is-closing" : ""}${isReturning ? " is-returning" : ""}`}
      style={overlayStyle}
      // 閉じる途中の面は見えているだけで、操作もフォーカスも受けない
      // The closing surface is only visible; it takes no input or focus
      inert={isClosing}
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
      {isClosing ? openContentRef.current : children}
    </div>,
    document.body,
  );
}
