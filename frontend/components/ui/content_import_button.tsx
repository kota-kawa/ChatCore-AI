// 「チャットを続ける」や「プロンプトをチャットで使う」など、取り込み系の操作に共通で使うボタン。待機・成功・失敗の状態に応じてラベルとアイコンを切り替える。
// Shared button for import-style actions such as continuing a chat or using a prompt in chat; switches label and icon by pending / success / error state.
import type { MouseEvent } from "react";

import type { ImportActionState } from "../../hooks/use_import_action";

export type ContentImportButtonVariant = "compact" | "labelled";

export type ContentImportButtonProps = {
  label: string;
  pendingLabel?: string;
  pending: boolean;
  state?: ImportActionState;
  successLabel?: string;
  errorLabel?: string;
  active?: boolean;
  disableWhenActive?: boolean;
  variant?: ContentImportButtonVariant;
  iconClass: string;
  pendingIconClass?: string;
  successIconClass?: string;
  errorIconClass?: string;
  className?: string;
  dataTooltip?: string;
  dataTooltipPlacement?: string;
  ariaPressed?: boolean;
  onClick: (event: MouseEvent<HTMLButtonElement>) => void;
};

/**
 * チャットの複製やプロンプトの取り込みで共通に使う、コンパクト版とラベル付き版のボタン。
 * Shared compact/labelled button surface for chat forks and prompt imports.
 */
export function ContentImportButton({
  label,
  pendingLabel,
  pending,
  state,
  successLabel,
  errorLabel,
  active = false,
  disableWhenActive = false,
  variant = "compact",
  iconClass,
  pendingIconClass = "bi-arrow-repeat",
  successIconClass = "bi-check-lg",
  errorIconClass = "bi-x-lg",
  className,
  dataTooltip,
  dataTooltipPlacement,
  ariaPressed,
  onClick,
}: ContentImportButtonProps) {
  // state が渡されたらそれを優先し、無ければ pending から待機中かどうかだけを決める
  // Prefer the explicit state when given; otherwise derive pending / idle from the pending flag
  const actionState = state ?? (pending ? "pending" : "idle");
  const isBusy = actionState === "pending" || pending;
  // 処理中、または active かつ disableWhenActive のときは押せなくする
  // Disable while busy, or when the button is active and disableWhenActive is set
  const isDisabled = isBusy || (disableWhenActive && active);
  const activeLabel = actionState === "pending"
    ? pendingLabel ?? label
    : actionState === "success"
      ? successLabel ?? label
      : actionState === "error"
        ? errorLabel ?? label
        : label;
  const activeIcon = actionState === "pending"
    ? pendingIconClass
    : actionState === "success"
      ? successIconClass
      : actionState === "error"
        ? errorIconClass
        : iconClass;
  const classes = [
    className,
    "content-import-button",
    `content-import-button--${variant}`,
    `content-import-button--${actionState}`,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <button
      type="button"
      className={classes}
      aria-label={activeLabel}
      aria-pressed={ariaPressed === undefined ? undefined : ariaPressed ? "true" : "false"}
      aria-disabled={isDisabled ? "true" : "false"}
      aria-busy={isBusy ? "true" : undefined}
      data-action-state={actionState}
      data-tooltip={dataTooltip ?? activeLabel}
      data-tooltip-placement={dataTooltipPlacement}
      disabled={isDisabled}
      onClick={onClick}
    >
      <i className={`bi ${activeIcon}`} aria-hidden="true"></i>
      {variant === "labelled" ? <span>{activeLabel}</span> : null}
    </button>
  );
}
