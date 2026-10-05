import { useCallback, useState } from "react";
import type { KeyedMutator } from "swr";

import { useTranslation } from "../../contexts/locale_context";
import { deleteMemo, loadMemoDetail, setMemoArchived, setMemoPinned, updateMemo } from "../../lib/memo/api";
import { autoMemoTitle, isAutoMemoTitle } from "../../lib/memo/auto_title";
import { toggleTaskMarker, type RenderedTask } from "../../lib/memo/list_editing";
import type { FlashState, MemoDetail, MemoListState, MemoSummary } from "../../lib/memo/types";
import { parseMemoText } from "../../lib/memo/utils";
import { showConfirmModal } from "../../scripts/core/alert_modal";
import { copyTextToClipboard } from "../../scripts/core/clipboard";

type UseMemoPageItemActionsParams = {
  mutate: KeyedMutator<MemoListState>;
  updateMemoListOptimistically: (
    updater: (memo: MemoSummary) => MemoSummary | null,
    targetIds: Iterable<string | number>,
  ) => Promise<void>;
  showFlash: (type: FlashState["type"], text: string) => void;
  selectedMemoId: string | number | undefined;
  patchSelectedMemoOptimistically: (memoId: string | number, patch: Partial<MemoDetail>) => void;
  refreshSelectedMemoIfNeeded: () => Promise<void>;
  startMemoDetailCloseAnimation: () => void;
};

// メモカード単体への操作（ピン・アーカイブ・削除・全文コピー）
// Actions on a single memo card (pin / archive / delete / copy full text)
export function useMemoPageItemActions({
  mutate,
  updateMemoListOptimistically,
  showFlash,
  selectedMemoId,
  patchSelectedMemoOptimistically,
  refreshSelectedMemoIfNeeded,
  startMemoDetailCloseAnimation,
}: UseMemoPageItemActionsParams) {
  const { t } = useTranslation();

  const [actionLoadingId, setActionLoadingId] = useState<string>("");
  const [copyingMemoId, setCopyingMemoId] = useState<string>("");

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
        await refreshSelectedMemoIfNeeded();
      } catch (error) {
        showFlash("error", error instanceof Error ? error.message : t("memo.pinUpdateFailed"));
        await mutate();
        await refreshSelectedMemoIfNeeded();
      }
    });
  }, [mutate, patchSelectedMemoOptimistically, refreshSelectedMemoIfNeeded, showFlash, updateMemoListOptimistically, withActionLoading]);

  // アーカイブ状態を切り替えるハンドラー
  // Handler to toggle the archived state
  const handleToggleArchive = useCallback(async (memo: MemoSummary) => {
    await withActionLoading(memo.id, async () => {
      const enabled = !memo.is_archived;
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
        showFlash("success", memo.is_archived ? t("memo.unarchivedSuccess") : t("memo.archivedSuccess"));
        await mutate();
        await refreshSelectedMemoIfNeeded();
      } catch (error) {
        showFlash("error", error instanceof Error ? error.message : t("memo.archiveUpdateFailed"));
        await mutate();
        await refreshSelectedMemoIfNeeded();
      }
    });
  }, [mutate, patchSelectedMemoOptimistically, refreshSelectedMemoIfNeeded, showFlash, updateMemoListOptimistically, withActionLoading]);

  // メモを削除するハンドラー
  // Handler to delete a memo
  const handleDeleteMemo = useCallback(async (memo: MemoSummary) => {
    const confirmed = await showConfirmModal(t("memo.deleteConfirm", { title: memo.title || t("memo.savedMemo") }));
    if (!confirmed) return;
    await withActionLoading(memo.id, async () => {
      await updateMemoListOptimistically(() => null, [memo.id]);
      try {
        await deleteMemo(memo.id, t("memo.memoDeleteFailed"));
        showFlash("success", t("memo.memoDeleted"));
        if (selectedMemoId && String(selectedMemoId) === String(memo.id)) startMemoDetailCloseAnimation();
        await mutate();
      } catch (error) {
        showFlash("error", error instanceof Error ? error.message : t("memo.memoDeleteFailed"));
        await mutate();
      }
    });
  }, [mutate, selectedMemoId, showFlash, startMemoDetailCloseAnimation, updateMemoListOptimistically, withActionLoading]);

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
    handleToggleMemoTask,
    copyMemoFullText,
  };
}
