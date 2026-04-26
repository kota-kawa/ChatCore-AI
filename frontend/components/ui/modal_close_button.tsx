import type { ButtonHTMLAttributes, ReactNode } from "react";

type ModalCloseButtonProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "type"> & {
  label: string;
  children?: ReactNode;
};

export function ModalCloseButton({
  children,
  className,
  label,
  ...buttonProps
}: ModalCloseButtonProps) {
  return (
    <button {...buttonProps} type="button" className={className} aria-label={label}>
      {children ?? <i className="bi bi-x-lg" aria-hidden="true"></i>}
    </button>
  );
}
