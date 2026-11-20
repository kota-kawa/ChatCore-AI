// 記憶の完全な削除（1 件）とすべての削除の、確認モーダルの状態と実行を持つ hook。MyContextPanel から使われる。
// 削除は確認モーダルの確定ボタンで初めて実行する。失敗はモーダルの中に出し、成功したら onDeleted で通知文を渡して一覧の再取得を任せる。
// Hook holding the confirmation-modal state and the execution of permanent deletion (one memory) and delete-all; used by MyContextPanel.
// A delete runs only on the modal's confirm button. A failure is shown inside the modal; on success onDeleted gets the notice text and the caller reloads the list.
import { useState } from "react";

import { useTranslation } from "../../contexts/locale_context";
import type { deleteAllContextFacts, deleteContextFact } from "../../lib/memo/context_api";
import type { ContextFact } from "../../lib/memo/context_types";

type UseContextFactDeletionOptions = {
  deleteOne: typeof deleteContextFact;
  deleteAll: typeof deleteAllContextFacts;
  onDeleted: (noticeText: string) => Promise<void> | void;
};

export function useContextFactDeletion({ deleteOne, deleteAll, onDeleted }: UseContextFactDeletionOptions) {
  const { t } = useTranslation();
  const [target, setTarget] = useState<ContextFact | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [errorText, setErrorText] = useState<string | null>(null);
  const [isAllOpen, setIsAllOpen] = useState(false);
  const [deletingAll, setDeletingAll] = useState(false);
  const [allErrorText, setAllErrorText] = useState<string | null>(null);

  const openDelete = (fact: ContextFact) => {
    setErrorText(null);
    setTarget(fact);
  };

  const closeDelete = () => {
    setTarget(null);
    setErrorText(null);
  };

  // 取得時の revision を添える。別の場所で更新された記憶は削除せず、エラーをモーダルに出す。
  // It sends the revision seen at load time; a memory changed elsewhere is not deleted and the error is shown in the modal.
  const confirmDelete = async () => {
    if (!target) return;
    setDeleting(true);
    setErrorText(null);
    try {
      await deleteOne(target.id, target.revision);
      setTarget(null);
      await onDeleted(t("memo.deleteFactDone"));
    } catch (err) {
      setErrorText(err instanceof Error ? err.message : t("memo.deleteFailed"));
    } finally {
      setDeleting(false);
    }
  };

  const openDeleteAll = () => {
    setAllErrorText(null);
    setIsAllOpen(true);
  };

  const closeDeleteAll = () => {
    setIsAllOpen(false);
    setAllErrorText(null);
  };

  // 自分の記憶・出典・候補をすべて削除する。自動で記憶する設定と回答に使う設定は変わらない。
  // Deletes all of the owner's memories, sources and candidates; the auto-save and use-in-answers settings are unchanged.
  const confirmDeleteAll = async () => {
    setDeletingAll(true);
    setAllErrorText(null);
    try {
      const deletedCount = await deleteAll();
      setIsAllOpen(false);
      await onDeleted(t("memo.deleteAllDone", { count: deletedCount }));
    } catch (err) {
      setAllErrorText(err instanceof Error ? err.message : t("memo.deleteFailed"));
    } finally {
      setDeletingAll(false);
    }
  };

  return {
    target,
    deleting,
    errorText,
    openDelete,
    closeDelete,
    confirmDelete,
    isAllOpen,
    deletingAll,
    allErrorText,
    openDeleteAll,
    closeDeleteAll,
    confirmDeleteAll,
  };
}
