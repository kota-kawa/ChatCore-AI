// 記憶 1 件を完全に削除する前の確認モーダル。無効化（再び覚えない。文面は残る）との違いを示し、削除は確認ボタンで初めて実行する。MyContextPanel から使われる。
// Confirmation modal before deleting one memory for good. It explains the difference from deactivating (not remembered again, wording kept); the delete runs only on the confirm button. Used by MyContextPanel.
import { useTranslation } from "../../contexts/locale_context";
import type { ContextFact } from "../../lib/memo/context_types";
import { ContextConfirmModal } from "./ContextConfirmModal";

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
  return (
    <ContextConfirmModal
      isOpen={fact !== null}
      idPrefix="context-delete"
      title={t("memo.deleteFactTitle")}
      busy={busy}
      errorText={errorText}
      confirmLabel={busy ? t("memo.deleting") : t("memo.deletePermanently")}
      onConfirm={onConfirm}
      onClose={onClose}
    >
      {fact && (
        <>
          <p className="memo-context-confirm__target">{fact.title}</p>
          <p className="memo-context-confirm__text" id="context-delete-description">
            {t("memo.deleteFactDescription")}
          </p>
        </>
      )}
    </ContextConfirmModal>
  );
}
