import type { Ref } from "react";

import { COPY_ERROR_ICON, COPY_IDLE_ICON, COPY_SUCCESS_ICON } from "../../lib/copy_feedback";
import { useCopyFeedback } from "../../hooks/use_copy_feedback";

// アプリ全体で共通のコピーボタン。
// - 見た目はアイコンのみ（ラベル文字を持たない）
// - 押すと数秒だけアイコンがチェックマークに変わり、その後元へ戻る
// コピー処理・タイミング・状態管理は useCopyFeedback に集約し、ここは描画だけを担う。
//
// The single copy button shared across the app.
// - Icon only (never a text label)
// - On click the icon becomes a check mark for a few seconds, then reverts
// The copy itself, the timing, and the state live in useCopyFeedback; this component only renders.

type TooltipMode = "title" | "data-tooltip" | "none";

type CopyButtonProps = {
  // 文字列を直接コピーする場合は getText を渡す。
  // トースト表示や共有URL生成など副作用を伴う場合は onCopy を使い、成否を boolean で返す。
  // Pass getText to copy a plain string. Use onCopy when the copy has side effects
  // (a toast, building a share URL, …) and return whether it succeeded.
  getText?: () => string;
  onCopy?: () => Promise<boolean> | boolean;

  // アイコンのみのボタンなのでアクセシブル名は必須。copied 時は copiedLabel（既定は label）へ。
  // この label はツールチップ文言も兼ねる。
  // The accessible name is required because the button is icon-only; it doubles as the tooltip text.
  label: string;
  copiedLabel?: string;
  // ツールチップの出し方（既定は title 属性）。
  tooltip?: TooltipMode;
  tooltipPlacement?: string;

  className?: string;
  // copied 状態のとき付けるクラス（例: "is-copied"）。
  copiedClassName?: string;
  // 成功／失敗時にボタンへ付けるクラス（例: "copy-btn--success" / "copy-btn--error"）。
  successClassName?: string;
  errorClassName?: string;

  // アイドル時のアイコン（bootstrap-icons、"bi-" 付き）。既定は共通のクリップボードアイコン。
  idleIcon?: string;

  // 非同期のコピー準備中（メモ全文の取得中など）に見せるスピナー用のアイコンクラス。
  // Spinner icon class shown while an async copy is being prepared (e.g. fetching memo text).
  busy?: boolean;
  busyIconClass?: string;

  id?: string;
  buttonRef?: Ref<HTMLButtonElement>;
  disabled?: boolean;
};

export function CopyButton({
  getText,
  onCopy,
  label,
  copiedLabel,
  tooltip = "title",
  tooltipPlacement,
  className,
  copiedClassName,
  successClassName,
  errorClassName,
  idleIcon = COPY_IDLE_ICON,
  busy = false,
  busyIconClass,
  id,
  buttonRef,
  disabled,
}: CopyButtonProps) {
  const { state, copied, failed, copy, run } = useCopyFeedback();

  const handleClick = () => {
    if (onCopy) {
      void run(onCopy);
      return;
    }
    if (getText) {
      void copy(getText);
    }
  };

  const iconClass = busy
    ? busyIconClass || idleIcon
    : copied
      ? COPY_SUCCESS_ICON
      : failed
        ? COPY_ERROR_ICON
        : idleIcon;

  const activeLabel = copied ? copiedLabel ?? label : label;

  const classes = [
    className,
    copied && copiedClassName ? copiedClassName : null,
    copied && successClassName ? successClassName : null,
    failed && errorClassName ? errorClassName : null,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <button
      type="button"
      id={id}
      ref={buttonRef}
      className={classes || undefined}
      aria-label={activeLabel}
      title={tooltip === "title" ? activeLabel : undefined}
      data-tooltip={tooltip === "data-tooltip" ? activeLabel : undefined}
      data-tooltip-placement={tooltip === "data-tooltip" ? tooltipPlacement : undefined}
      disabled={disabled || busy || state !== "idle"}
      onClick={handleClick}
    >
      <i className={`bi ${iconClass}`} aria-hidden="true"></i>
    </button>
  );
}
