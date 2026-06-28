import { useEffect, useRef, useState } from "react";
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
}: {
  value: string;
  onChange: (value: string) => void;
  options: SelectOption[];
  className?: string;
  disabled?: boolean;
  id?: string;
}) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number; width: number } | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLUListElement>(null);

  const toggleOpen = () => {
    if (disabled) return;
    if (!open && triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect();
      setPos({ top: rect.bottom + 6, left: rect.left, width: rect.width });
    }
    setOpen((v) => !v);
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
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <span className="memo-select__label">{selectedLabel}</span>
        <i className="bi bi-chevron-down memo-select__chevron" aria-hidden="true" />
      </button>
      {open && pos && createPortal(
        <ul
          ref={menuRef}
          className="memo-select__menu"
          role="listbox"
          style={{ position: "fixed", top: pos.top, left: pos.left, minWidth: pos.width, zIndex: 99999 }}
        >
          {options.map((opt) => {
            const isSel = opt.value === value;
            return (
              <li
                key={opt.value}
                role="option"
                aria-selected={isSel}
                className={`memo-select__option${isSel ? " is-selected" : ""}`}
                onClick={() => { onChange(opt.value); setOpen(false); }}
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
