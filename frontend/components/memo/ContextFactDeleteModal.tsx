// 記憶 1 件を完全に削除する前の確認モーダル。無効化（再び覚えない。文面は残る）との違いを示し、削除は確認ボタンで初めて実行する。MyContextPanel から使われる。
// Confirmation modal before deleting one memory for good. It explains the difference from deactivating (not remembered again, wording kept); the delete runs only on the confirm button. Used by MyContextPanel.
import { useCallback, useRef } from "react";

import { useTranslation } from "../../contexts/locale_context";
import { useBodyScrollLock } from "../../hooks/use_body_scroll_lock";
import type { ContextFact } from "../../lib/memo/context_types";
import { ModalCloseButton } from "../ui/modal_close_button";
import { ModalShell } from "../ui/modal_shell";

type ContextFactDeleteModalProps = {
  // 削除しようとしている記憶。null のあいだは閉じている。
  // The memory about to be deleted; closed while null.
  fact: ContextFact | null;
  busy: boolean;
  errorText: string | null;
  onConfirm: () => void;
  onClose: () => void;
};

export function ContextFactDeleteModal({ fact, busy, errorText, onConfirm, onClose }: ContextFactDeleteModalProps) {
  const { t } = useTranslation();
  const cancelRef = useRef<HTMLButtonElement | null>(null);
  // 取り消せない操作なので、最初のフォーカスは安全側のキャンセルに置く。
  // The action cannot be undone, so the first focus goes to the safe choice, Cancel.
  const getInitialFocus = useCallback(() => cancelRef.current, []);
  useBodyScrollLock(fact !== null);

  return (
    <ModalShell
      isOpen={fact !== null}
      onClose={onClose}
      id="context-delete-modal"
      className="cc-modal memo-modal-scope memo-context-modal memo-context-confirm"
      labelledBy="context-delete-title"
      dismissDisabled={busy}
      getInitialFocus={getInitialFocus}
    >
      {fact && (
        <div className="cc-modal__panel cc-modal__panel--sm" aria-describedby="context-delete-description" aria-busy={busy} tabIndex={-1}>
          <header className="cc-modal__header">
            <div className="cc-modal__heading">
              <h2 className="cc-modal__title" id="context-delete-title">{t("memo.deleteFactTitle")}</h2>
            </div>
            <ModalCloseButton label={t("common.close")} onClick={onClose} disabled={busy} />
          </header>
          <div className="cc-modal__body">
            {errorText && (
              <div className="cc-modal__notice memo-context-modal__error" role="alert">
                {errorText}
              </div>
            )}
            <p className="memo-context-confirm__target">{fact.title}</p>
            <p className="memo-context-confirm__text" id="context-delete-description">
              {t("memo.deleteFactDescription")}
            </p>
          </div>
          <footer className="cc-modal__footer">
            <button ref={cancelRef} type="button" className="cc-modal__btn" onClick={onClose} disabled={busy}>
              {t("common.cancel")}
            </button>
            <button type="button" className="cc-modal__btn cc-modal__btn--primary" onClick={onConfirm} disabled={busy}>
              {busy ? t("memo.deleting") : t("memo.deletePermanently")}
            </button>
          </footer>
        </div>
      )}
    </ModalShell>
  );
}
