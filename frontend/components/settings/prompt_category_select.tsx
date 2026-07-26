import {
  useEffect,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent
} from "react";

import { getCategoryLabelOrFallback } from "../../scripts/prompt_share/prompt_category_registry";
import { PROMPT_CATEGORY_OPTIONS } from "../prompt_share/prompt_share_page_constants";

// キーボード操作に対応したアクセシブルなカテゴリ選択コンポーネント
// Accessible category select component with full keyboard navigation support
export function PromptCategorySelect({
  selectId,
  value,
  disabled,
  onChange
}: {
  selectId: string;
  value: string;
  disabled: boolean;
  onChange: (value: string) => void;
}) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  // 各オプションボタンへの参照を保持し、フォーカス移動に使う
  // Holds refs to each option button so keyboard navigation can move focus programmatically
  const optionRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const [isOpen, setIsOpen] = useState(false);
  // 値は保存用の安定キー、表示はレジストリ解決したラベル。空キーは「未選択」を表す。
  // The value is the stable key; the label is resolved from the registry. Empty key means unselected.
  const selectedValue = value || "";
  // 現在値がレジストリにない（移行前の値など）場合は先頭に追加して一覧に含める
  // Prepend the current value when the registry does not know it (e.g. a pre-migration value)
  const isKnownValue = PROMPT_CATEGORY_OPTIONS.some((option) => option.value === selectedValue);
  const categoryOptions = isKnownValue
    ? PROMPT_CATEGORY_OPTIONS
    : [
        { value: selectedValue, label: getCategoryLabelOrFallback(selectedValue) },
        ...PROMPT_CATEGORY_OPTIONS
      ];
  const selectedIndex = Math.max(
    0,
    categoryOptions.findIndex((option) => option.value === selectedValue)
  );
  const selectedLabel = categoryOptions[selectedIndex]?.label ?? "未選択";
  const [activeIndex, setActiveIndex] = useState(selectedIndex);
  const listboxId = `${selectId}-menu`;

  // 選択値が外部から変わったときにアクティブインデックスを同期する
  // Keep activeIndex in sync when the selected value changes externally
  useEffect(() => {
    setActiveIndex(selectedIndex);
  }, [selectedIndex]);

  // ドロップダウンが開いている間、外側クリックで閉じるためのグローバルリスナーを登録する
  // Register a global pointer-down listener to close the dropdown when clicking outside
  useEffect(() => {
    if (!isOpen) {
      return;
    }

    const handlePointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    document.addEventListener("pointerdown", handlePointerDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
    };
  }, [isOpen]);

  // activeIndex が変わるたびに対応するオプションにフォーカスを移す
  // Move focus to the option at activeIndex whenever it changes while the list is open
  useEffect(() => {
    if (isOpen) {
      optionRefs.current[activeIndex]?.focus();
    }
  }, [activeIndex, isOpen]);

  // 指定インデックスでリストを開く — 範囲外にならないようクランプする
  // Open the list at the specified index, clamped within valid bounds
  const openAt = (index: number) => {
    setActiveIndex(Math.min(Math.max(index, 0), categoryOptions.length - 1));
    setIsOpen(true);
  };

  // 選択を確定してリストを閉じ、トリガーボタンにフォーカスを戻す
  // Commit the selection, close the list, and return focus to the trigger button
  const selectOption = (index: number) => {
    const nextOption = categoryOptions[index];
    if (!nextOption) {
      return;
    }
    onChange(nextOption.value);
    setIsOpen(false);
    triggerRef.current?.focus();
  };

  // トリガーボタンのキーボードイベント — 矢印キーでリストを開く
  // Keyboard handler for the trigger button — arrow keys open the dropdown
  const handleTriggerKeyDown = (event: ReactKeyboardEvent<HTMLButtonElement>) => {
    if (disabled) {
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      openAt(isOpen ? activeIndex + 1 : selectedIndex);
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      openAt(isOpen ? activeIndex - 1 : selectedIndex);
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openAt(selectedIndex);
    }
  };

  // オプション項目のキーボードイベント — Home/End でリストの端へ移動し、Escape で閉じる
  // Keyboard handler for option items — Home/End jump to list edges; Escape closes the list
  const handleOptionKeyDown = (event: ReactKeyboardEvent<HTMLButtonElement>, index: number) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      openAt(index + 1);
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      openAt(index - 1);
      return;
    }
    if (event.key === "Home") {
      event.preventDefault();
      openAt(0);
      return;
    }
    if (event.key === "End") {
      event.preventDefault();
      openAt(categoryOptions.length - 1);
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      setIsOpen(false);
      triggerRef.current?.focus();
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      selectOption(index);
    }
  };

  return (
    <div ref={rootRef} className="prompt-category-select">
      {/* ネイティブ select はスクリーンリーダー向けにのみ保持し、見た目は非表示にする / Native select is kept for screen-reader compatibility but hidden visually */}
      <select
        id={selectId}
        className="prompt-category-select__native"
        value={selectedValue}
        disabled={disabled}
        onChange={(event) => {
          onChange(event.target.value);
        }}
      >
        {categoryOptions.map((category) => (
          <option key={category.value} value={category.value}>
            {category.label}
          </option>
        ))}
      </select>

      <button
        ref={triggerRef}
        type="button"
        className={`prompt-category-select__trigger${isOpen ? " is-open" : ""}`}
        aria-haspopup="listbox"
        aria-expanded={isOpen ? "true" : "false"}
        aria-controls={listboxId}
        aria-label="カテゴリを選択"
        disabled={disabled}
        onClick={() => {
          setActiveIndex(selectedIndex);
          setIsOpen((previous) => !previous);
        }}
        onKeyDown={handleTriggerKeyDown}
      >
        <span className="min-w-0 flex-1 truncate">{selectedLabel}</span>
        <i
          className={`bi bi-chevron-down prompt-category-select__chevron${isOpen ? " is-open" : ""}`}
          aria-hidden="true"
        ></i>
      </button>

      {/* ドロップダウンリスト — isOpen が true の間だけレンダリングする / Dropdown list — rendered only while isOpen is true */}
      {isOpen ? (
        <div
          id={listboxId}
          role="listbox"
          aria-label="カテゴリを選択"
          className="prompt-category-select__menu"
        >
          {categoryOptions.map((category, index) => {
            const selected = selectedValue === category.value;
            return (
              <button
                key={category.value}
                ref={(node) => {
                  optionRefs.current[index] = node;
                }}
                type="button"
                role="option"
                aria-selected={selected ? "true" : "false"}
                tabIndex={activeIndex === index ? 0 : -1}
                className={`prompt-category-select__option${selected ? " is-selected" : ""}`}
                onClick={() => {
                  selectOption(index);
                }}
                onKeyDown={(event) => {
                  handleOptionKeyDown(event, index);
                }}
              >
                <span className="min-w-0 truncate">{category.label}</span>
                {selected ? <i className="bi bi-check-lg shrink-0" aria-hidden="true"></i> : null}
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
