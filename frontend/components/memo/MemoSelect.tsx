import { useEffect, useId, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { createPortal } from "react-dom";

import type { SelectOption } from "../../lib/memo/types";

// ---------------------------------------------------------------------------
// MemoSelect – custom styled dropdown
// ---------------------------------------------------------------------------

// カスタムセレクトボックス（ドロップダウン）コンポーネント
// Custom select box (dropdown) component
export function MemoSelect({
  value,
  onChange,
  options,
  className,
  disabled,
  id,
  ariaLabel,
}: {
  value: string;
  onChange: (value: string) => void;
  options: SelectOption[];
  className?: string;
  disabled?: boolean;
  id?: string;
  ariaLabel?: string;
}) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number; width: number } | null>(null);
  // 開いている間、矢印キーでハイライトしている選択肢のインデックス（未確定の候補、選択とは別）
  // Index of the option currently highlighted by the arrow keys while open (a candidate, not yet committed)
  const [activeIndex, setActiveIndex] = useState(0);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLUListElement>(null);
  const generatedId = useId();
  const listboxId = `${id ?? generatedId}-listbox`;
  const getOptionId = (index: number) => `${listboxId}-option-${index}`;

  const selectedIndex = Math.max(0, options.findIndex((o) => o.value === value));

  // メニューを開き、現在選択中の項目をハイライト候補として初期化する
  // Open the menu and seed the highlighted candidate with the currently selected option
  const openMenu = () => {
    if (disabled || !triggerRef.current) return;
    const rect = triggerRef.current.getBoundingClientRect();
    setPos({ top: rect.bottom + 6, left: rect.left, width: rect.width });
    setActiveIndex(selectedIndex);
    setOpen(true);
  };

  // メニューを閉じ、必要に応じてトリガーボタンへフォーカスを戻す
  // Close the menu and, unless told otherwise, return focus to the trigger button
  const closeMenu = (refocusTrigger = true) => {
    setOpen(false);
    if (refocusTrigger) triggerRef.current?.focus();
  };

  const toggleOpen = () => {
    if (disabled) return;
    if (open) {
      closeMenu();
    } else {
      openMenu();
    }
  };

  // トリガーボタン上での矢印キー操作でメニューを開く（ネイティブselect互換）
  // Arrow keys on the trigger button open the menu, matching native <select> behavior
  const handleTriggerKeyDown = (event: ReactKeyboardEvent<HTMLButtonElement>) => {
    if (disabled || open) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      openMenu();
    }
  };

  // WAI-ARIAのlistboxパターンに準拠した矢印キー・Home/End・Enter・Escapeのハンドリング
  // Implements the WAI-ARIA listbox keyboard pattern: arrows, Home/End, Enter, and Escape
  const handleMenuKeyDown = (event: ReactKeyboardEvent<HTMLUListElement>) => {
    if (options.length === 0) return;
    const lastIndex = options.length - 1;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((current) => (current >= lastIndex ? 0 : current + 1));
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((current) => (current <= 0 ? lastIndex : current - 1));
      return;
    }
    if (event.key === "Home") {
      event.preventDefault();
      setActiveIndex(0);
      return;
    }
    if (event.key === "End") {
      event.preventDefault();
      setActiveIndex(lastIndex);
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      closeMenu();
      return;
    }
    if (event.key === "Tab") {
      // Tabでの離脱は閉じるだけにして、フォーカス移動自体はブラウザ標準に任せる
      // Tabbing away just closes the menu; let the browser move focus normally
      closeMenu(false);
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      const option = options[activeIndex];
      if (option) onChange(option.value);
      closeMenu();
    }
  };

  // セレクトメニュー外のクリックとスクロールを検知して閉じる副作用
  // Effect to close the select menu when clicking outside or scrolling
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!triggerRef.current?.contains(e.target as Node) && !menuRef.current?.contains(e.target as Node))
        setOpen(false);
    };
    const onScroll = () => setOpen(false);
    document.addEventListener("mousedown", onDown);
    window.addEventListener("scroll", onScroll, true);
    return () => {
      document.removeEventListener("mousedown", onDown);
      window.removeEventListener("scroll", onScroll, true);
    };
  }, [open]);

  // 開いたときはリストボックス自体にフォーカスを移し、矢印キー操作をすぐ受け付ける
  // Move focus onto the listbox itself when it opens, so arrow keys work immediately
  useEffect(() => {
    if (!open) return;
    const raf = window.requestAnimationFrame(() => {
      menuRef.current?.focus();
    });
    return () => window.cancelAnimationFrame(raf);
  }, [open]);

  const selectedLabel = options.find((o) => o.value === value)?.label ?? "";

  return (
    <div
      id={id}
      className={`memo-select${open ? " is-open" : ""}${disabled ? " is-disabled" : ""}${className ? ` ${className}` : ""}`}
    >
      <button
        ref={triggerRef}
        type="button"
        className="memo-select__trigger"
        onClick={toggleOpen}
        onKeyDown={handleTriggerKeyDown}
        disabled={disabled}
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listboxId : undefined}
      >
        <span className="memo-select__label">{selectedLabel}</span>
        <i className="bi bi-chevron-down memo-select__chevron" aria-hidden="true" />
      </button>
      {open && pos && createPortal(
        <ul
          ref={menuRef}
          id={listboxId}
          className="memo-select__menu"
          role="listbox"
          tabIndex={-1}
          aria-activedescendant={options[activeIndex] ? getOptionId(activeIndex) : undefined}
          onKeyDown={handleMenuKeyDown}
          style={{ position: "fixed", top: pos.top, left: pos.left, minWidth: pos.width, zIndex: 99999 }}
        >
          {options.map((opt, index) => {
            const isSel = opt.value === value;
            const isActive = index === activeIndex;
            return (
              <li
                key={opt.value}
                id={getOptionId(index)}
                role="option"
                aria-selected={isSel}
                className={`memo-select__option${isSel ? " is-selected" : ""}${isActive ? " is-active" : ""}`}
                onMouseEnter={() => setActiveIndex(index)}
                onClick={() => { onChange(opt.value); closeMenu(); }}
              >
                {isSel && <i className="bi bi-check2 memo-select__check" aria-hidden="true" />}
                {opt.label}
              </li>
            );
          })}
        </ul>,
        document.body,
      )}
    </div>
  );
}
