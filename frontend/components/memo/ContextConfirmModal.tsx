// 記憶の画面の削除の確認モーダルに共通の枠（見出し・エラー・本文・キャンセルと確認のボタン）。本文と確認ボタンの文言・有効条件は呼び出し側が決める。ContextFactDeleteModal と ContextDeleteAllModal から使われる。
// Shared frame of the memory screen's delete confirmation modals (heading, error, body, and Cancel / confirm buttons). The body and the confirm button's label and enabled state come from the caller. Used by ContextFactDeleteModal and ContextDeleteAllModal.
import { useCallback, useRef, type ReactNode } from "react";

import { useTranslation } from "../../contexts/locale_context";
import { useBodyScrollLock } from "../../hooks/use_body_scroll_lock";
import { ModalCloseButton } from "../ui/modal_close_button";
import { ModalShell } from "../ui/modal_shell";

type ContextConfirmModalProps = {
  isOpen: boolean;
  // DOM の id の接頭辞。"<idPrefix>-modal"・"<idPrefix>-title"・"<idPrefix>-description" を使う。
  // Prefix of the DOM ids: "<idPrefix>-modal", "<idPrefix>-title" and "<idPrefix>-description" are used.
  idPrefix: string;
  title: string;
  busy: boolean;
  errorText: string | null;
  confirmLabel: string;
  confirmDisabled?: boolean;
  onConfirm: () => void;
  onClose: () => void;
  // 最初のフォーカス。省略時は取り消せない操作なので安全側のキャンセルに置く。
  // The first focus; by default Cancel, the safe choice, since the action cannot be undone.
  getInitialFocus?: () => HTMLElement | null;
  // 本文。説明の段落には id="<idPrefix>-description" を付ける（aria-describedby の参照先）。
  // The body; the description paragraph carries id="<idPrefix>-description" (the aria-describedby target).
  children: ReactNode;
};

export function ContextConfirmModal({
  isOpen,
  idPrefix,
  title,
  busy,
  errorText,
  confirmLabel,
  confirmDisabled = false,
  onConfirm,
  onClose,
  getInitialFocus,
  children,
}: ContextConfirmModalProps) {
  const { t } = useTranslation();
  const cancelRef = useRef<HTMLButtonElement | null>(null);
  const defaultInitialFocus = useCallback(() => cancelRef.current, []);
  useBodyScrollLock(isOpen);

  return (
    <ModalShell
      isOpen={isOpen}
      onClose={onClose}
      id={`${idPrefix}-modal`}
      className="cc-modal memo-modal-scope memo-context-modal memo-context-confirm"
      labelledBy={`${idPrefix}-title`}
      dismissDisabled={busy}
      getInitialFocus={getInitialFocus ?? defaultInitialFocus}
    >
      <div className="cc-modal__panel cc-modal__panel--sm" aria-describedby={`${idPrefix}-description`} aria-busy={busy} tabIndex={-1}>
        <header className="cc-modal__header">
          <div className="cc-modal__heading">
            <h2 className="cc-modal__title" id={`${idPrefix}-title`}>{title}</h2>
          </div>
          <ModalCloseButton label={t("common.close")} onClick={onClose} disabled={busy} />
        </header>
        <div className="cc-modal__body">
          {errorText && (
            <div className="cc-modal__notice memo-context-modal__error" role="alert">
              {errorText}
            </div>
          )}
          {children}
        </div>
        <footer className="cc-modal__footer">
          <button ref={cancelRef} type="button" className="cc-modal__btn" onClick={onClose} disabled={busy}>
            {t("common.cancel")}
          </button>
          <button
            type="button"
            className="cc-modal__btn cc-modal__btn--primary"
            onClick={onConfirm}
            disabled={busy || confirmDisabled}
          >
            {confirmLabel}
          </button>
        </footer>
      </div>
    </ModalShell>
  );
}
