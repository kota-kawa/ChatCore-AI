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

/** Shared compact/labelled button surface for chat forks and prompt imports. */
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
  const actionState = state ?? (pending ? "pending" : "idle");
  const isBusy = actionState === "pending" || pending;
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
