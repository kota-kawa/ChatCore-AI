// すべての記憶を削除する前の確認モーダル。消える件数と、取り消せないことを示し、確認のチェックを入れるまで削除ボタンを押せなくする。MyContextPanel から使われる。
// Confirmation modal before deleting all memories. It shows how many go and that it cannot be undone, and keeps the delete button disabled until the confirmation box is checked. Used by MyContextPanel.
import { useCallback, useEffect, useRef, useState } from "react";

import { useTranslation } from "../../contexts/locale_context";
import { ContextConfirmModal } from "./ContextConfirmModal";

type ContextDeleteAllModalProps = {
  isOpen: boolean;
  // 有効な記憶の件数。無効化済みの記憶の件数は一覧が持たないので、文面では「無効化済みの記憶も」と添える。
  // The number of active memories; the list does not know how many deactivated ones there are, so the text adds "and deactivated ones".
  activeCount: number;
  busy: boolean;
  errorText: string | null;
  onConfirm: () => void;
  onClose: () => void;
};

export function ContextDeleteAllModal({ isOpen, activeCount, busy, errorText, onConfirm, onClose }: ContextDeleteAllModalProps) {
  const { t } = useTranslation();
  const [acknowledged, setAcknowledged] = useState(false);
  const checkboxRef = useRef<HTMLInputElement | null>(null);
  const getInitialFocus = useCallback(() => checkboxRef.current, []);

  // 開き直すたびに確認のチェックを外し、前回のチェックのまま削除できないようにする。
  // The confirmation box is cleared on every open, so a previous check cannot carry over into a delete.
  useEffect(() => {
    if (isOpen) setAcknowledged(false);
  }, [isOpen]);

  return (
    <ContextConfirmModal
      isOpen={isOpen}
      idPrefix="context-delete-all"
      title={t("memo.deleteAllTitle")}
      busy={busy}
      errorText={errorText}
      confirmLabel={busy ? t("memo.deleting") : t("memo.deleteAllConfirm")}
      confirmDisabled={!acknowledged}
      onConfirm={onConfirm}
      onClose={onClose}
      getInitialFocus={getInitialFocus}
    >
      <p className="memo-context-confirm__text" id="context-delete-all-description">
        {t("memo.deleteAllDescription", { count: activeCount })}
      </p>
      <p className="memo-context-confirm__text">{t("memo.deleteAllSettingsKept")}</p>
      <label className="memo-context-confirm__acknowledge">
        <input
          ref={checkboxRef}
          type="checkbox"
          checked={acknowledged}
          onChange={(event) => setAcknowledged(event.target.checked)}
          disabled={busy}
        />
        <span>{t("memo.deleteAllAcknowledge")}</span>
      </label>
    </ContextConfirmModal>
  );
}
