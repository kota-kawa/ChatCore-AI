import type { ButtonHTMLAttributes, ReactNode } from "react";

// モーダル閉じるボタンのprops型定義（buttonのtype属性を除いたHTMLButtonAttributesを継承）
// Props type definition for the modal close button (extends HTMLButtonAttributes excluding type)
type ModalCloseButtonProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "type"> & {
  label: string;
  children?: ReactNode;
};

// アクセシブルなモーダル閉じるボタン（デフォルトは×アイコン、childrenで上書き可能）
// Accessible modal close button (defaults to × icon, overridable with children)
export function ModalCloseButton({
  children,
  className,
  label,
  ...buttonProps
}: ModalCloseButtonProps) {
  return (
    <button {...buttonProps} type="button" className={className} aria-label={label}>
      {/* childrenがなければデフォルトの×アイコンを表示する / Show default × icon when no children provided */}
      {children ?? <i className="bi bi-x-lg" aria-hidden="true"></i>}
    </button>
  );
}
