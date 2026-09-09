import type { ButtonHTMLAttributes, ReactNode, Ref } from "react";

// モーダル閉じるボタンのprops型定義（buttonのtype属性を除いたHTMLButtonAttributesを継承）
// Props type definition for the modal close button (extends HTMLButtonAttributes excluding type)
type ModalCloseButtonProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "type"> & {
  label: string;
  children?: ReactNode;
  // 初期フォーカスなどでボタン要素を参照したい呼び出し元向け / For callers that need the element (e.g. initial focus)
  ref?: Ref<HTMLButtonElement>;
};

// アクセシブルなモーダル閉じるボタン（デフォルトは×アイコン、childrenで上書き可能）
// 見た目は共通モーダル面の `cc-modal__close` を既定にし、className で上書きできる。
// Accessible modal close button (defaults to × icon, overridable with children).
// Styled as the shared `cc-modal__close` by default; className overrides it.
export function ModalCloseButton({
  children,
  className = "cc-modal__close",
  label,
  ref,
  ...buttonProps
}: ModalCloseButtonProps) {
  return (
    <button {...buttonProps} ref={ref} type="button" className={className} aria-label={label}>
      {/* childrenがなければデフォルトの×アイコンを表示する / Show default × icon when no children provided */}
      {children ?? <i className="bi bi-x-lg" aria-hidden="true"></i>}
    </button>
  );
}
