import { useState, useRef, useEffect, useLayoutEffect, useCallback, type ReactNode } from "react";

import { useTranslation } from "../../contexts/locale_context";
import {
  clampModalPosition,
  keepPositionIfUnchanged,
  positionModalAwayFromRect,
  type Position,
  type ViewportBounds,
} from "../../lib/ui/draggable_modal_position";
import { readSessionJson, writeSessionJson } from "../../lib/utils";

// ドラッグ可能モーダルのprops型定義
// Props type definition for the draggable modal
type DraggableModalProps = {
  isOpen: boolean;
  onClose: () => void;
  title?: string;
  children: ReactNode;
  initialX?: number;
  initialY?: number;
  positionStorageKey?: string;
  initialFocusSelector?: string;
  avoidTextInputFocusOnTouch?: boolean;
  avoidElementSelector?: string;
  avoidElementMinViewportWidth?: number;
};

// モーダルを閉じるアニメーションの時間（ミリ秒）
// Duration of the modal close animation (milliseconds)
const CLOSE_ANIMATION_MS = 320;

// 値が有限な数値かどうかを型ガードで確認する
// Type guard to check if a value is a finite number
function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function getViewportBounds(): ViewportBounds {
  const visualViewport = window.visualViewport;
  return {
    left: visualViewport?.offsetLeft ?? 0,
    top: visualViewport?.offsetTop ?? 0,
    width: visualViewport?.width ?? window.innerWidth,
    height: visualViewport?.height ?? window.innerHeight,
  };
}

function isTouchViewport() {
  return window.innerWidth <= 640 || window.matchMedia?.("(pointer: coarse)").matches === true;
}

// ヘッダーをドラッグして画面内を自由に移動できるモーダルコンポーネント
// Modal component that can be freely moved within the screen by dragging its header
export function DraggableModal({
  isOpen,
  onClose,
  title,
  children,
  initialX = 100,
  initialY = 100,
  positionStorageKey,
  initialFocusSelector,
  avoidTextInputFocusOnTouch = false,
  avoidElementSelector,
  avoidElementMinViewportWidth = 0,
}: DraggableModalProps) {
  const { t } = useTranslation();
  const fallbackTitle = t("agent.header");
  // モーダルの現在位置（px）
  // Current position of the modal (px)
  const [position, setPosition] = useState<Position>({ x: initialX, y: initialY });
  const [isDragging, setIsDragging] = useState(false);
  // ドラッグ開始時のポインターとモーダル位置の差分
  // Offset between pointer and modal position when dragging starts
  const [dragOffset, setDragOffset] = useState({ x: 0, y: 0 });
  // SSRハイドレーション完了フラグ
  // Flag indicating SSR hydration is complete
  const [hydrated, setHydrated] = useState(false);
  // 閉じるアニメーション中もDOMを保持するフラグ
  // Flag to keep the DOM during the close animation
  const [shouldRender, setShouldRender] = useState(isOpen);
  // DOMの準備と位置補正が済んでから入場アニメーションを始める
  // Start the entry animation only after the DOM and position are ready
  const [isEntryReady, setIsEntryReady] = useState(false);
  const modalRef = useRef<HTMLDivElement>(null);
  // モーダルを閉じた後にフォーカスを戻す要素のref
  // Ref to the element that should receive focus after the modal closes
  const previouslyFocusedRef = useRef<HTMLElement | null>(null);

  // マウント時にセッションストレージから前回の位置を復元する
  // Restore the previous position from session storage on mount
  useEffect(() => {
    if (positionStorageKey) {
      const stored = readSessionJson<Position | null>(positionStorageKey, null);
      if (stored && isFiniteNumber(stored.x) && isFiniteNumber(stored.y)) {
        setPosition(stored);
      }
    }
    setHydrated(true);
  }, [positionStorageKey]);

  // 位置が変わったらセッションストレージに保存する（ハイドレーション後のみ）
  // Save position to session storage when it changes (only after hydration)
  useEffect(() => {
    if (!hydrated || !positionStorageKey) return;
    writeSessionJson(positionStorageKey, position);
  }, [hydrated, positionStorageKey, position]);

  // 閉じるアニメーションが完了するまでDOMを保持する
  // Keep the DOM until the close animation completes
  useLayoutEffect(() => {
    if (isOpen) {
      setShouldRender(true);
      return undefined;
    }

    const timer = window.setTimeout(() => {
      setShouldRender(false);
      setIsEntryReady(false);
    }, CLOSE_ANIMATION_MS);

    return () => {
      window.clearTimeout(timer);
    };
  }, [isOpen]);

  // モーダルがビューポートからはみ出さないよう位置を制限する
  // Clamp position so the modal stays within the viewport
  const clampPosition = useCallback((nextPosition: { x: number; y: number }) => {
    const modal = modalRef.current;
    return clampModalPosition(
      nextPosition,
      { width: modal?.offsetWidth || 360, height: modal?.offsetHeight || 520 },
      getViewportBounds(),
    );
  }, []);

  // 開くときは、指定された固定要素（チャコボタンなど）との重なりも避ける
  // On open, also avoid overlapping a specified fixed element such as the Chaco launcher
  const resolveOpenPosition = useCallback((nextPosition: Position) => {
    const modal = modalRef.current;
    const viewport = getViewportBounds();
    const avoidedElement = avoidElementSelector && viewport.width >= avoidElementMinViewportWidth
      ? document.querySelector<HTMLElement>(avoidElementSelector)
      : null;
    const avoidedRect = avoidedElement?.getBoundingClientRect();

    return positionModalAwayFromRect(
      nextPosition,
      { width: modal?.offsetWidth || 360, height: modal?.offsetHeight || 520 },
      viewport,
      avoidedRect,
    );
  }, [avoidElementMinViewportWidth, avoidElementSelector]);

  // マウスドラッグ開始ハンドラー（閉じるボタンクリックは除外）
  // Mouse drag start handler (excluding close button clicks)
  const handleMouseDown = (e: React.MouseEvent<HTMLDivElement>) => {
    if ((e.target as HTMLElement).closest(".modal-close-btn")) return;

    setIsDragging(true);
    setDragOffset({
      x: e.clientX - position.x,
      y: e.clientY - position.y,
    });
  };

  // タッチ/ペンデバイスのドラッグ開始ハンドラー
  // Drag start handler for touch/pen devices
  const handlePointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if ((event.target as HTMLElement).closest(".modal-close-btn")) return;
    if (event.pointerType === "mouse") return;

    // ポインターをキャプチャしてドラッグ中に外れないようにする
    // Capture the pointer to keep tracking even if it leaves the element
    event.currentTarget.setPointerCapture(event.pointerId);
    setIsDragging(true);
    setDragOffset({
      x: event.clientX - position.x,
      y: event.clientY - position.y,
    });
  };

  // タッチ/ペンのドラッグ移動ハンドラー
  // Drag move handler for touch/pen devices
  const handlePointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!isDragging || event.pointerType === "mouse") return;
    setPosition(clampPosition({
      x: event.clientX - dragOffset.x,
      y: event.clientY - dragOffset.y,
    }));
  };

  // タッチ/ペンのドラッグ終了ハンドラー
  // Drag end handler for touch/pen devices
  const handlePointerUp = (event: React.PointerEvent<HTMLDivElement>) => {
    if (event.pointerType === "mouse") return;
    setIsDragging(false);
  };

  // マウスドラッグ移動ハンドラー（windowレベルで監視）
  // Mouse drag move handler (monitored at the window level)
  const handleMouseMove = useCallback(
    (e: MouseEvent) => {
      if (isDragging) {
        setPosition(clampPosition({
          x: e.clientX - dragOffset.x,
          y: e.clientY - dragOffset.y,
        }));
      }
    },
    [isDragging, dragOffset, clampPosition]
  );

  // マウスボタンリリースハンドラー
  // Mouse button release handler
  const handleMouseUp = useCallback(() => {
    setIsDragging(false);
  }, []);

  // ドラッグ中のみwindowにマウスイベントリスナーを登録する
  // Register mouse event listeners on the window only while dragging
  useEffect(() => {
    if (isDragging) {
      window.addEventListener("mousemove", handleMouseMove);
      window.addEventListener("mouseup", handleMouseUp);
    } else {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    }
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  }, [isDragging, handleMouseMove, handleMouseUp]);

  // 初回描画前に位置を確定し、非表示の準備フレーム後にアニメーションを開始する
  // Resolve position before paint, then animate after a hidden preparation frame
  useLayoutEffect(() => {
    if (!shouldRender || !isOpen) return undefined;

    setPosition((current) => keepPositionIfUnchanged(current, resolveOpenPosition(current)));
    let animationFrame = window.requestAnimationFrame(() => {
      animationFrame = window.requestAnimationFrame(() => {
        setIsEntryReady(true);
      });
    });

    return () => window.cancelAnimationFrame(animationFrame);
  }, [isOpen, resolveOpenPosition, shouldRender]);

  // ウィンドウリサイズとVisual Viewport変化時にモーダルをビューポート内に収める
  // Keep the modal within the viewport on window resize and Visual Viewport changes
  useEffect(() => {
    if (!shouldRender || !isOpen) return undefined;

    const keepModalInViewport = () => {
      setPosition((current) => keepPositionIfUnchanged(current, resolveOpenPosition(current)));
    };

    window.addEventListener("resize", keepModalInViewport);
    window.visualViewport?.addEventListener("resize", keepModalInViewport);
    window.visualViewport?.addEventListener("scroll", keepModalInViewport);

    return () => {
      window.removeEventListener("resize", keepModalInViewport);
      window.visualViewport?.removeEventListener("resize", keepModalInViewport);
      window.visualViewport?.removeEventListener("scroll", keepModalInViewport);
    };
  }, [isOpen, shouldRender, resolveOpenPosition]);

  // モーダルが開いたとき、最初のフォーカス可能な要素にフォーカスを移す
  // Move focus to the first focusable element when the modal opens
  useEffect(() => {
    if (!isOpen || !isEntryReady) return undefined;

    previouslyFocusedRef.current = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    const timer = window.setTimeout(() => {
      let requestedTarget = initialFocusSelector
        ? modalRef.current?.querySelector<HTMLElement>(initialFocusSelector)
        : null;
      if (
        avoidTextInputFocusOnTouch
        && isTouchViewport()
        && (requestedTarget instanceof HTMLInputElement || requestedTarget instanceof HTMLTextAreaElement)
      ) {
        requestedTarget = null;
      }
      const focusTarget = requestedTarget ?? modalRef.current?.querySelector<HTMLElement>(
        "input:not([disabled]), textarea:not([disabled]), button:not([disabled]), [tabindex]:not([tabindex='-1'])"
      );
      focusTarget?.focus({ preventScroll: true });
    }, 0);

    return () => {
      window.clearTimeout(timer);
    };
  }, [avoidTextInputFocusOnTouch, initialFocusSelector, isEntryReady, isOpen]);

  // モーダルが閉じたとき、フォーカスを元の要素に戻す
  // Return focus to the previously focused element when the modal closes
  useEffect(() => {
    if (isOpen) return undefined;
    const previouslyFocused = previouslyFocusedRef.current;
    if (previouslyFocused?.isConnected) {
      previouslyFocused.focus();
    }
    previouslyFocusedRef.current = null;
    return undefined;
  }, [isOpen]);

  // Escキーでモーダルを閉じるイベントリスナー（キャプチャフェーズで登録して優先度を高める）
  // Escape key listener to close the modal (registered in capture phase for higher priority)
  useEffect(() => {
    if (!isOpen) return undefined;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      onClose();
    };
    document.addEventListener("keydown", handleKeyDown, true);
    return () => {
      document.removeEventListener("keydown", handleKeyDown, true);
    };
  }, [isOpen, onClose]);

  // 閉じるアニメーション完了後はDOMから削除する
  // Remove from DOM after close animation completes
  if (!shouldRender) return null;

  const animationClass = isOpen
    ? isEntryReady ? "is-open" : "is-preparing"
    : "is-closing";

  return (
    <div
      ref={modalRef}
      className={`ai-agent-modal global-ai-agent-modal ${animationClass}`}
      role="dialog"
      aria-modal="false"
      aria-label={title || fallbackTitle}
      aria-hidden={!isOpen || !isEntryReady ? true : undefined}
      style={{
        position: "fixed",
        left: `${position.x}px`,
        top: `${position.y}px`,
        zIndex: 1000,
        cursor: isDragging ? "grabbing" : "auto",
      }}
    >
      {/* ドラッグ可能なヘッダー / Draggable header */}
      <div
        className="ai-agent-modal-header"
        onMouseDown={handleMouseDown}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerUp}
        style={{ cursor: "grab", touchAction: "none" }}
      >
        <span className="ai-agent-modal-title">{title}</span>
        <button
          type="button"
          className="modal-close-btn"
          onClick={onClose}
          aria-label={t("agent.close")}
        >
          <i className="bi bi-x-lg"></i>
        </button>
      </div>
      <div className="ai-agent-modal-content">
        {children}
      </div>
    </div>
  );
}
