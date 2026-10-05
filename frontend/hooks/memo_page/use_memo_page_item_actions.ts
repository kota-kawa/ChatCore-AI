import { useCallback, useState } from "react";
import type { KeyedMutator } from "swr";

import { useTranslation } from "../../contexts/locale_context";
import { deleteMemo, emptyMemoTrash, loadMemoDetail, purgeMemo, restoreMemo, setMemoArchived, setMemoPinned, updateMemo } from "../../lib/memo/api";
import { autoMemoTitle, isAutoMemoTitle } from "../../lib/memo/auto_title";
import { toggleTaskMarker, type RenderedTask } from "../../lib/memo/list_editing";
import type { FlashAction, FlashState, MemoDetail, MemoListState, MemoSummary } from "../../lib/memo/types";
import { parseMemoText } from "../../lib/memo/utils";
import { showConfirmModal } from "../../scripts/core/alert_modal";
import { copyTextToClipboard } from "../../scripts/core/clipboard";

type UseMemoPageItemActionsParams = {
  mutate: KeyedMutator<MemoListState>;
  updateMemoListOptimistically: (
    updater: (memo: MemoSummary) => MemoSummary | null,
    targetIds: Iterable<string | number>,
  ) => Promise<void>;
  showFlash: (type: FlashState["type"], text: string, action?: FlashAction) => void;
  selectedMemoId: string | number | undefined;
  patchSelectedMemoOptimistically: (memoId: string | number, patch: Partial<MemoDetail>) => void;
  refreshSelectedMemoIfNeeded: (memoId: string | number) => Promise<void>;
  // 開いている詳細の未保存の編集を保存する / Saves the pending edits of the open detail
  saveSelectedMemoEdits: () => Promise<boolean>;
  startMemoDetailCloseAnimation: () => void;
};

// メモカード単体への操作（ピン・アーカイブ・ゴミ箱への移動と復元・完全削除・全文コピー）とゴミ箱を空にする操作
// Actions on a single memo card (pin / archive / move to trash, restore, delete for good / copy full text) and emptying the trash
export function useMemoPageItemActions({
  mutate,
  updateMemoListOptimistically,
  showFlash,
  selectedMemoId,
  patchSelectedMemoOptimistically,
  refreshSelectedMemoIfNeeded,
  saveSelectedMemoEdits,
  startMemoDetailCloseAnimation,
}: UseMemoPageItemActionsParams) {
  const { t } = useTranslation();

  const [actionLoadingId, setActionLoadingId] = useState<string>("");
  const [copyingMemoId, setCopyingMemoId] = useState<string>("");
  const [emptyingTrash, setEmptyingTrash] = useState(false);

  const withActionLoading = useCallback(async (memoId: string | number, action: () => Promise<void>) => {
    const id = String(memoId);
    setActionLoadingId(id);
    try { await action(); } finally { setActionLoadingId(""); }
  }, []);

  // ピン留め状態を切り替えるハンドラー
  // Handler to toggle the pinned state
  const handleTogglePin = useCallback(async (memo: MemoSummary) => {
    await withActionLoading(memo.id, async () => {
      const enabled = !memo.is_pinned;
      const pinnedAt = enabled ? new Date().toISOString() : null;
      await updateMemoListOptimistically(
        (current) => ({
          ...current,
          is_pinned: enabled,
          pinned_at: pinnedAt,
        }),
        [memo.id],
      );
      patchSelectedMemoOptimistically(memo.id, { is_pinned: enabled, pinned_at: pinnedAt });
      try {
        await setMemoPinned(memo.id, enabled, t("memo.pinUpdateFailed"));
        showFlash("success", memo.is_pinned ? t("memo.unpinnedSuccess") : t("memo.pinnedSuccess"));
        await mutate();
        await refreshSelectedMemoIfNeeded(memo.id);
      } catch (error) {
        showFlash("error", error instanceof Error ? error.message : t("memo.pinUpdateFailed"));
        await mutate();
        await refreshSelectedMemoIfNeeded(memo.id);
      }
    });
  }, [mutate, patchSelectedMemoOptimistically, refreshSelectedMemoIfNeeded, showFlash, updateMemoListOptimistically, withActionLoading]);

  // アーカイブ状態を設定する。通常の操作には「元に戻す」を付け、押されたときは逆の状態をこの関数で
  // 設定し直す（取り消し自体には「元に戻す」を付けない）
  // Sets the archived state. A normal action carries an undo that sets the opposite state through this
  // same function (an undo does not carry an undo of its own)
  const setArchived = useCallback(async (memo: MemoSummary, enabled: boolean, isUndo: boolean) => {
    await withActionLoading(memo.id, async () => {
      const archivedAt = enabled ? new Date().toISOString() : null;
      await updateMemoListOptimistically(
        (current) => ({
          ...current,
          is_archived: enabled,
          archived_at: archivedAt,
        }),
        [memo.id],
      );
      patchSelectedMemoOptimistically(memo.id, { is_archived: enabled, archived_at: archivedAt });
      try {
        await setMemoArchived(memo.id, enabled, t("memo.archiveUpdateFailed"));
        const text = enabled ? t("memo.archivedSuccess") : t("memo.unarchivedSuccess");
        showFlash("success", text, isUndo ? undefined : { label: t("memo.undo"), onAction: () => setArchived(memo, !enabled, true) });
        await mutate();
        await refreshSelectedMemoIfNeeded(memo.id);
      } catch (error) {
        showFlash("error", error instanceof Error ? error.message : t("memo.archiveUpdateFailed"));
        await mutate();
        await refreshSelectedMemoIfNeeded(memo.id);
      }
    });
  }, [mutate, patchSelectedMemoOptimistically, refreshSelectedMemoIfNeeded, showFlash, t, updateMemoListOptimistically, withActionLoading]);

  // アーカイブ状態を切り替えるハンドラー
  // Handler to toggle the archived state
  const handleToggleArchive = useCallback(
    (memo: MemoSummary) => setArchived(memo, !memo.is_archived, false),
    [setArchived],
  );

  // ゴミ箱から元に戻す。削除直後の「元に戻す」とゴミ箱画面の「元に戻す」で共通。共有リンクは
  // ゴミ箱へ移した時点で無効になっていて自動では再開しないので、共有していたメモには通知で一言添える
  // Restores a memo from the trash, shared by the undo right after a delete and the trash screen's
  // restore button. The share link was revoked when the memo went to the trash and does not resume
  // on its own, so the notice says so for a memo that had one
  const handleRestoreMemo = useCallback(async (memo: MemoSummary) => {
    await withActionLoading(memo.id, async () => {
      await updateMemoListOptimistically(() => null, [memo.id]);
      try {
        await restoreMemo(memo.id, t("memo.restoreFailed"));
        // ゴミ箱へ移すと共有は解除される。直前の削除を取り消す場合は削除前のメモを持っているので、
        // 共有中だったときだけ知らせる。ゴミ箱の一覧のメモは解除後の状態しか分からないため、
        // 共有したことがあるメモには知らせる
        // Trashing a memo turns its sharing off. An undo right after the delete still holds the
        // memo from before, so it mentions sharing only when that memo was shared. A memo listed in
        // the trash only shows the state after the revoke, so any memo that was ever shared gets the note
        const wasShared = memo.deleted_at ? Boolean(memo.share_token) : Boolean(memo.is_active);
        showFlash("success", wasShared ? t("memo.restoredShareOff") : t("memo.restored"));
      } catch (error) {
        showFlash("error", error instanceof Error ? error.message : t("memo.restoreFailed"));
      }
      await mutate();
    });
  }, [mutate, showFlash, t, updateMemoListOptimistically, withActionLoading]);

  // ゴミ箱の 1 件を完全に削除する。取り消せないので確認を挟む
  // Permanently deletes one trashed memo. It cannot be undone, so confirm first
  const handlePurgeMemo = useCallback(async (memo: MemoSummary) => {
    const confirmed = await showConfirmModal(t("memo.purgeConfirm", { title: memo.title || t("memo.savedMemo") }));
    if (!confirmed) return;
    await withActionLoading(memo.id, async () => {
      await updateMemoListOptimistically(() => null, [memo.id]);
      try {
        await purgeMemo(memo.id, t("memo.purgeFailed"));
        showFlash("success", t("memo.purged"));
      } catch (error) {
        showFlash("error", error instanceof Error ? error.message : t("memo.purgeFailed"));
      }
      await mutate();
    });
  }, [mutate, showFlash, t, updateMemoListOptimistically, withActionLoading]);

  // ゴミ箱をすべて完全に削除する。絞り込み中の一部ではなくゴミ箱の全件が対象
  // Permanently deletes everything in the trash (all of it, not just the filtered part)
  const handleEmptyTrash = useCallback(async () => {
    if (emptyingTrash) return;
    const confirmed = await showConfirmModal(t("memo.emptyTrashConfirm"));
    if (!confirmed) return;
    setEmptyingTrash(true);
    try {
      const deleted = await emptyMemoTrash(t("memo.emptyTrashFailed"));
      showFlash("success", t("memo.trashEmptied", { count: deleted }));
    } catch (error) {
      showFlash("error", error instanceof Error ? error.message : t("memo.emptyTrashFailed"));
    } finally {
      setEmptyingTrash(false);
    }
    await mutate();
  }, [emptyingTrash, mutate, showFlash, t]);

  // メモをゴミ箱へ移すハンドラー。確認は挟まず、通知の「元に戻す」で取り消せる
  // Handler to move a memo to the trash. No confirmation: the notice's undo takes it back
  const handleDeleteMemo = useCallback(async (memo: MemoSummary) => {
    await withActionLoading(memo.id, async () => {
      // 詳細を開いたまま削除するときは、打ったばかりの編集を先に保存する。保存せずに消すと、
      // 「元に戻す」で戻ってくるのが編集前の内容になる（保存できない内容ならそのまま削除する）
      // Deleting from the open detail saves what was just typed first; otherwise undo would bring
      // back the text from before the edit (content that cannot be saved is deleted as it is)
      const isOpenInDetail = Boolean(selectedMemoId) && String(selectedMemoId) === String(memo.id);
      if (isOpenInDetail) await saveSelectedMemoEdits();
      await updateMemoListOptimistically(() => null, [memo.id]);
      try {
        await deleteMemo(memo.id, t("memo.memoDeleteFailed"));
        showFlash("success", t("memo.movedToTrash"), { label: t("memo.undo"), onAction: () => handleRestoreMemo(memo) });
        if (isOpenInDetail) startMemoDetailCloseAnimation();
        await mutate();
      } catch (error) {
        showFlash("error", error instanceof Error ? error.message : t("memo.memoDeleteFailed"));
        await mutate();
      }
    });
  }, [handleRestoreMemo, mutate, saveSelectedMemoEdits, selectedMemoId, showFlash, startMemoDetailCloseAnimation, t, updateMemoListOptimistically, withActionLoading]);

  // 一覧のカードに見えているチェック欄を切り替える。カードは本文の先頭だけを表示しているので、
  // 全文を取り直し、見えている欄が全文の先頭と同じ並び・同じ文字であることを確かめてから書き換える。
  // 食い違えば（別の端末で編集された等）別の行を書き換えかねないので、何もせず一覧を取り直す。
  // カードの表示は先に切り替え、失敗したら取り直した一覧で元に戻す。タイトルは、本文の最初の行
  // から付いた自動タイトルのときだけ付け直して送る（それ以外で送ると、タイトル未設定の古いメモに
  // 表示用の仮の題が保存されてしまう）。
  // Toggles a checkbox shown on a list card. A card shows only the head of the body, so the full
  // text is fetched and the visible boxes are checked against its head (order and text) before it
  // is rewritten. On a mismatch (edited elsewhere, for example) the wrong line could change, so
  // nothing is written and the list is reloaded. The card flips first and the reloaded list puts
  // it back on failure. The title is sent only to re-derive one that came from the body's first
  // line (sending it otherwise would store the display placeholder as the title of an old
  // untitled memo).
  const handleToggleMemoTask = useCallback(async (memo: MemoSummary, index: number, rendered: RenderedTask[]) => {
    await withActionLoading(memo.id, async () => {
      const excerpt = parseMemoText(memo.excerpt);
      const optimisticExcerpt = toggleTaskMarker(excerpt, index, rendered);
      if (optimisticExcerpt !== null) {
        await updateMemoListOptimistically((current) => ({
          ...current,
          excerpt: optimisticExcerpt,
          title: isAutoMemoTitle(current.title, excerpt) ? autoMemoTitle(optimisticExcerpt) : current.title,
        }), [memo.id]);
      }
      try {
        const detail = await loadMemoDetail(memo.id);
        const body = detail?.ai_response || "";
        const next = toggleTaskMarker(body, index, rendered, true);
        if (next === null) {
          showFlash("error", t("memo.taskToggleFailed"));
        } else {
          // 本文の最初の行から付いた自動タイトルは、その行のチェックが変われば付け直す
          // A title derived from the first line is re-derived when that line's checkbox changes
          const title = isAutoMemoTitle(detail?.title, body) ? { title: autoMemoTitle(next) } : {};
          await updateMemo(memo.id, { ...title, ai_response: next }, t("memo.memoUpdateFailed"));
        }
      } catch (error) {
        showFlash("error", error instanceof Error ? error.message : t("memo.memoUpdateFailed"));
      }
      await mutate();
    });
  }, [mutate, showFlash, updateMemoListOptimistically, withActionLoading]);

  // コピー成否は共通の CopyButton がアイコン表示に使う。取得中のスピナーだけここで面倒を見る。
  // The shared CopyButton uses the returned success flag for its icon; only the "loading" spinner is tracked here.
  const copyMemoFullText = useCallback(async (memo: MemoSummary): Promise<boolean> => {
    const memoId = String(memo.id);
    setCopyingMemoId(memoId);
    try {
      const detail = await loadMemoDetail(memo.id);
      const fullText = detail?.ai_response || memo.excerpt || "";
      const content = `${detail?.title || memo.title || t("memo.savedMemo")}\n\n${parseMemoText(fullText)}`;
      await copyTextToClipboard(content.trim());
      return true;
    } catch (error) {
      showFlash("error", error instanceof Error ? error.message : t("memo.copyFailed"));
      return false;
    }
    finally { setCopyingMemoId(""); }
  }, [showFlash]);

  return {
    actionLoadingId,
    copyingMemoId,
    handleTogglePin,
    handleToggleArchive,
    handleDeleteMemo,
    handleRestoreMemo,
    handlePurgeMemo,
    handleEmptyTrash,
    emptyingTrash,
    handleToggleMemoTask,
    copyMemoFullText,
  };
}
