import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { KeyedMutator } from "swr";

import { useTranslation } from "../../contexts/locale_context";
import { loadMemoDetail, updateMemo } from "../../lib/memo/api";
import { DETAIL_AUTOSAVE_DELAY_MS, MEMO_DETAIL_CLOSE_ANIMATION_MS } from "../../lib/memo/constants";
import type {
  Collection,
  DetailSaveStatus,
  FlashState,
  MemoDetail,
  MemoListState,
  MemoUpdateInput,
} from "../../lib/memo/types";
import { parseMemoText } from "../../lib/memo/utils";
import { copyTextToClipboard } from "../../scripts/core/clipboard";

type UseMemoPageDetailParams = {
  collections: Collection[];
  mutate: KeyedMutator<MemoListState>;
  showFlash: (type: FlashState["type"], text: string) => void;
};

// メモ詳細モーダルの状態と操作（開閉・編集・自動保存・メモエージェント）
// State and actions for the memo detail modal (open/close, editing, autosave, memo agent)
export function useMemoPageDetail({ collections, mutate, showFlash }: UseMemoPageDetailParams) {
  const { t } = useTranslation();

  // Detail modal
  const [selectedMemo, setSelectedMemo] = useState<MemoDetail | null>(null);
  const [isMemoDetailClosing, setIsMemoDetailClosing] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [detailPreviewMode, setDetailPreviewMode] = useState(true);
  const [detailEditTitle, setDetailEditTitle] = useState("");
  const [detailEditCollectionId, setDetailEditCollectionId] = useState<number | null>(null);
  const [detailEditAiResponse, setDetailEditAiResponse] = useState("");
  const [detailEditBackgroundColor, setDetailEditBackgroundColor] = useState<string | null>(null);
  const [detailSaveStatus, setDetailSaveStatus] = useState<DetailSaveStatus>("idle");
  const [detailSaveError, setDetailSaveError] = useState("");
  const [isMemoAgentOpen, setIsMemoAgentOpen] = useState(false);
  const detailAutoSaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const memoDetailCloseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const detailSaveSequenceRef = useRef(0);

  // アンマウント時に閉じるアニメーションのタイマーを破棄する
  // Drop the pending close-animation timer on unmount
  useEffect(() => {
    return () => {
      if (memoDetailCloseTimerRef.current) {
        clearTimeout(memoDetailCloseTimerRef.current);
        memoDetailCloseTimerRef.current = null;
      }
    };
  }, []);

  // メモ詳細が閉じられた際に自動保存タイマーをクリアする副作用
  // Effect to clear the auto-save timer when the memo detail is closed
  useEffect(() => {
    if (selectedMemo) return;
    if (detailAutoSaveTimerRef.current) {
      clearTimeout(detailAutoSaveTimerRef.current);
      detailAutoSaveTimerRef.current = null;
    }
    detailSaveSequenceRef.current += 1;
    setDetailPreviewMode(true);
    setDetailEditTitle("");
    setDetailEditCollectionId(null);
    setDetailEditAiResponse("");
    setDetailEditBackgroundColor(null);
    setDetailSaveStatus("idle");
    setDetailSaveError("");
  }, [selectedMemo]);

  const patchSelectedMemoOptimistically = useCallback((memoId: string | number, patch: Partial<MemoDetail>) => {
    setSelectedMemo((current) => (
      current && String(current.id) === String(memoId)
        ? { ...current, ...patch }
        : current
    ));
  }, []);

  const refreshSelectedMemoIfNeeded = useCallback(async () => {
    if (!selectedMemo?.id) return;
    try {
      const refreshed = await loadMemoDetail(selectedMemo.id);
      if (refreshed) setSelectedMemo(refreshed);
    } catch { return; }
  }, [selectedMemo?.id]);

  const detailHasUnsavedChanges = useMemo(() => {
    if (!selectedMemo) return false;
    return (
      detailEditTitle !== (selectedMemo.title || "") ||
      detailEditCollectionId !== (selectedMemo.collection_id ?? null) ||
      detailEditAiResponse !== (selectedMemo.ai_response || "") ||
      detailEditBackgroundColor !== (selectedMemo.background_color ?? null)
    );
  }, [
    detailEditAiResponse,
    detailEditBackgroundColor,
    detailEditCollectionId,
    detailEditTitle,
    selectedMemo,
  ]);

  const clearDetailAutoSaveTimer = useCallback(() => {
    if (!detailAutoSaveTimerRef.current) return;
    clearTimeout(detailAutoSaveTimerRef.current);
    detailAutoSaveTimerRef.current = null;
  }, []);

  const cancelMemoDetailCloseAnimation = useCallback(() => {
    if (!memoDetailCloseTimerRef.current) return;
    clearTimeout(memoDetailCloseTimerRef.current);
    memoDetailCloseTimerRef.current = null;
  }, []);

  const startMemoDetailCloseAnimation = useCallback(() => {
    if (memoDetailCloseTimerRef.current) return;
    clearDetailAutoSaveTimer();
    setIsMemoAgentOpen(false);
    setIsMemoDetailClosing(true);
    memoDetailCloseTimerRef.current = setTimeout(() => {
      memoDetailCloseTimerRef.current = null;
      setSelectedMemo(null);
      setIsMemoDetailClosing(false);
    }, MEMO_DETAIL_CLOSE_ANIMATION_MS);
  }, [clearDetailAutoSaveTimer]);

  const openMemoDetail = useCallback(async (memoId: string | number) => {
    cancelMemoDetailCloseAnimation();
    setIsMemoDetailClosing(false);
    setDetailError("");
    setDetailLoading(true);
    setDetailPreviewMode(true);
    setDetailSaveStatus("idle");
    setDetailSaveError("");
    setIsMemoAgentOpen(false);
    if (detailAutoSaveTimerRef.current) {
      clearTimeout(detailAutoSaveTimerRef.current);
      detailAutoSaveTimerRef.current = null;
    }
    detailSaveSequenceRef.current += 1;
    try {
      const memo = await loadMemoDetail(memoId);
      if (!memo) { setDetailError(t("memo.memoDetailFailed")); return; }
      setDetailEditTitle(memo.title || "");
      setDetailEditCollectionId(memo.collection_id ?? null);
      setDetailEditAiResponse(memo.ai_response || "");
      setDetailEditBackgroundColor(memo.background_color ?? null);
      setSelectedMemo(memo);
      setDetailSaveStatus("saved");
    } catch (error) {
      setDetailError(error instanceof Error ? error.message : t("memo.memoDetailFailed"));
    } finally {
      setDetailLoading(false);
    }
  }, [cancelMemoDetailCloseAnimation]);

  const saveDetailEdit = useCallback(async () => {
    if (!selectedMemo?.id || !detailHasUnsavedChanges) return true;
    if (!detailEditAiResponse.trim()) {
      setDetailSaveStatus("error");
      setDetailSaveError(t("memo.bodyRequired"));
      return false;
    }
    const snapshot = {
      title: detailEditTitle,
      collectionId: detailEditCollectionId,
      aiResponse: detailEditAiResponse,
      backgroundColor: detailEditBackgroundColor,
    };
    const requestId = ++detailSaveSequenceRef.current;
    setDetailSaveStatus("saving");
    setDetailSaveError("");
    try {
      const body: MemoUpdateInput = {
        title: snapshot.title,
        ai_response: snapshot.aiResponse,
      };

      if (snapshot.backgroundColor) {
        body.background_color = snapshot.backgroundColor;
      } else {
        body.clear_background_color = true;
      }

      if (collections.length > 0) {
        if (snapshot.collectionId !== null) {
          body.collection_id = snapshot.collectionId;
        } else {
          body.clear_collection = true;
        }
      }

      const updatedMemo = await updateMemo(selectedMemo.id, body, t("memo.memoUpdateFailed"));
      if (requestId === detailSaveSequenceRef.current) {
        if (updatedMemo) {
          // Keep the exact text the user submitted as the saved baseline
          // instead of the server's normalized response. This prevents the
          // autosave from rewriting what the user is actively editing (for
          // example, a leading blank line they just added), so the editor
          // only ever changes in response to the user's own input.
          setSelectedMemo({
            ...updatedMemo,
            title: snapshot.title,
            ai_response: snapshot.aiResponse,
            collection_id: snapshot.collectionId,
            background_color: snapshot.backgroundColor,
          });
        }
        setDetailSaveStatus("saved");
        setDetailSaveError("");
      }
      void mutate();
      return true;
    } catch (error) {
      if (requestId === detailSaveSequenceRef.current) {
        setDetailSaveStatus("error");
        setDetailSaveError(error instanceof Error ? error.message : t("memo.memoUpdateFailed"));
      }
      return false;
    }
  }, [
    collections.length,
    detailEditAiResponse,
    detailEditBackgroundColor,
    detailEditCollectionId,
    detailEditTitle,
    detailHasUnsavedChanges,
    mutate,
    selectedMemo?.id,
  ]);

  const closeMemoDetail = useCallback(async () => {
    if (memoDetailCloseTimerRef.current) return;
    clearDetailAutoSaveTimer();
    if (detailHasUnsavedChanges) {
      const saved = await saveDetailEdit();
      if (!saved) return;
    }
    startMemoDetailCloseAnimation();
  }, [clearDetailAutoSaveTimer, detailHasUnsavedChanges, saveDetailEdit, startMemoDetailCloseAnimation]);

  const openMemoAgent = useCallback(async () => {
    if (!selectedMemo?.id) return;
    if (detailHasUnsavedChanges) {
      const saved = await saveDetailEdit();
      if (!saved) return;
    }
    setIsMemoAgentOpen(true);
  }, [detailHasUnsavedChanges, saveDetailEdit, selectedMemo?.id]);

  useEffect(() => {
    clearDetailAutoSaveTimer();
    if (!selectedMemo || !detailHasUnsavedChanges) return;
    if (!detailEditAiResponse.trim()) {
      setDetailSaveStatus("error");
      setDetailSaveError(t("memo.bodyRequired"));
      return;
    }

    setDetailSaveStatus("idle");
    setDetailSaveError("");
    detailAutoSaveTimerRef.current = setTimeout(() => {
      void saveDetailEdit();
    }, DETAIL_AUTOSAVE_DELAY_MS);

    return clearDetailAutoSaveTimer;
  }, [
    clearDetailAutoSaveTimer,
    detailEditAiResponse,
    detailHasUnsavedChanges,
    saveDetailEdit,
    selectedMemo,
  ]);

  useEffect(() => {
    if (!selectedMemo) setIsMemoAgentOpen(false);
  }, [selectedMemo]);

  const copyDetailFullText = useCallback(async (): Promise<boolean> => {
    const fullText = detailEditAiResponse || selectedMemo?.ai_response || "";
    const content = `${detailEditTitle || selectedMemo?.title || t("memo.savedMemo")}\n\n${parseMemoText(fullText)}`;
    try {
      await copyTextToClipboard(content.trim());
      return true;
    } catch (error) {
      showFlash("error", error instanceof Error ? error.message : t("memo.copyFailed"));
      return false;
    }
  }, [detailEditAiResponse, detailEditTitle, selectedMemo?.ai_response, selectedMemo?.title, showFlash]);

  return {
    selectedMemo,
    isMemoDetailClosing,
    detailLoading,
    detailError,
    detailPreviewMode,
    setDetailPreviewMode,
    detailEditTitle,
    setDetailEditTitle,
    detailEditCollectionId,
    setDetailEditCollectionId,
    detailEditAiResponse,
    setDetailEditAiResponse,
    detailEditBackgroundColor,
    setDetailEditBackgroundColor,
    detailSaveStatus,
    detailSaveError,
    isMemoAgentOpen,
    setIsMemoAgentOpen,
    detailHasUnsavedChanges,
    openMemoDetail,
    closeMemoDetail,
    openMemoAgent,
    saveDetailEdit,
    copyDetailFullText,
    patchSelectedMemoOptimistically,
    refreshSelectedMemoIfNeeded,
    startMemoDetailCloseAnimation,
  };
}
