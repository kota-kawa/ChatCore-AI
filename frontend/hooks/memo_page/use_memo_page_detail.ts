import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { KeyedMutator } from "swr";

import { useTranslation } from "../../contexts/locale_context";
import { loadMemoDetail, updateMemo } from "../../lib/memo/api";
import { autoMemoTitle, isAutoMemoTitle } from "../../lib/memo/auto_title";
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
import { showConfirmModal } from "../../scripts/core/alert_modal";
import { copyTextToClipboard } from "../../scripts/core/clipboard";

type UseMemoPageDetailParams = {
  collections: Collection[];
  mutate: KeyedMutator<MemoListState>;
  showFlash: (type: FlashState["type"], text: string) => void;
};

// サーバーの応答を受け取れなかった失敗か。fetch は接続できないと TypeError を、
// resilientFetch はタイムアウトで DOMException を投げる。
// Whether the failure means no response came back: fetch throws a TypeError when it cannot
// connect, and resilientFetch throws a DOMException on timeout.
function isConnectionFailure(error: unknown) {
  return error instanceof TypeError || error instanceof DOMException || navigator.onLine === false;
}

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
  // 送信中の保存とその内容。同じ内容の保存が重ねて要求されたら、送り直さずこの結果を返す
  // The save in flight and what it carries; a repeated request for the same content reuses it
  const detailSaveInFlightRef = useRef<{ key: string; result: Promise<boolean> } | null>(null);

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

  // タイトルが本文の最初の行から自動で付いたものなら、本文の書き換えに合わせて付け直す。
  // そのままにすると、最初の行を直したあとも古い行がタイトルとして残り、一覧に同じ内容が
  // 題と本文の両方で並ぶ。利用者が付けたタイトルには触れない。
  // When the title is the one derived from the body's first line, re-derive it as the body
  // changes. Left alone, the old line would stay as the title after the first line is edited and
  // the list would show the content twice. A title the user wrote is never touched.
  const updateDetailBody = useCallback((nextBody: string) => {
    if (isAutoMemoTitle(detailEditTitle, detailEditAiResponse)) setDetailEditTitle(autoMemoTitle(nextBody));
    setDetailEditAiResponse(nextBody);
  }, [detailEditAiResponse, detailEditTitle]);

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

  // 開けたかどうかを返す。失敗時は詳細が開かず画面に何も出ないので、ここで通知する
  // Resolves to whether the memo opened. On failure the detail never opens and nothing would
  // show, so the error is surfaced here
  const openMemoDetail = useCallback(async (memoId: string | number): Promise<boolean> => {
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
      if (!memo) {
        setDetailError(t("memo.memoDetailFailed"));
        showFlash("error", t("memo.memoDetailFailed"));
        return false;
      }
      setDetailEditTitle(memo.title || "");
      setDetailEditCollectionId(memo.collection_id ?? null);
      setDetailEditAiResponse(memo.ai_response || "");
      setDetailEditBackgroundColor(memo.background_color ?? null);
      // 本文が空なら読むものが無いので、最初から書ける状態で開く
      // An empty body has nothing to read, so open straight into the editor
      setDetailPreviewMode(Boolean(memo.ai_response?.trim()));
      setSelectedMemo(memo);
      setDetailSaveStatus("saved");
      return true;
    } catch (error) {
      const message = error instanceof Error ? error.message : t("memo.memoDetailFailed");
      setDetailError(message);
      showFlash("error", message);
      return false;
    } finally {
      setDetailLoading(false);
    }
  }, [cancelMemoDetailCloseAnimation, showFlash]);

  const sendDetailEdit = useCallback(async (
    memoId: string | number,
    snapshot: { title: string; collectionId: number | null; aiResponse: string; backgroundColor: string | null },
    options: { keepalive?: boolean },
  ) => {
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

      const updatedMemo = await updateMemo(memoId, body, t("memo.memoUpdateFailed"), options);
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
        // サーバーに届かなかった失敗は英語の例外文言しか持たないので、状況が分かる文言に置き換える
        // A request that never reached the server only carries an English exception text; say what happened instead
        setDetailSaveError(
          isConnectionFailure(error) ? t("memo.saveConnectionFailed") : error instanceof Error ? error.message : t("memo.memoUpdateFailed"),
        );
      }
      return false;
    }
  }, [collections.length, mutate]);

  const saveDetailEdit = useCallback(async (options: { keepalive?: boolean } = {}) => {
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
    // ページを離れるときは pagehide と visibilitychange が続けて来るうえ、自動保存の送信中に
    // 重なることもある。同じ内容を二重に送ると、後発の失敗が先発の成功を打ち消してしまう
    // Leaving the page fires pagehide and visibilitychange back to back, possibly on top of an
    // autosave in flight. Sending the same content twice lets a late failure undo an early success
    const saveKey = JSON.stringify([selectedMemo.id, snapshot]);
    if (detailSaveInFlightRef.current?.key === saveKey) return detailSaveInFlightRef.current.result;
    const result = sendDetailEdit(selectedMemo.id, snapshot, options);
    detailSaveInFlightRef.current = { key: saveKey, result };
    try {
      return await result;
    } finally {
      if (detailSaveInFlightRef.current?.result === result) detailSaveInFlightRef.current = null;
    }
  }, [
    detailEditAiResponse,
    detailEditBackgroundColor,
    detailEditCollectionId,
    detailEditTitle,
    detailHasUnsavedChanges,
    selectedMemo?.id,
    sendDetailEdit,
  ]);

  const closeMemoDetail = useCallback(async () => {
    if (memoDetailCloseTimerRef.current) return;
    clearDetailAutoSaveTimer();
    if (detailHasUnsavedChanges) {
      if (!detailEditAiResponse.trim()) {
        // 本文が空のメモは保存できない。閉じられなくなるより、最後に保存した内容を残して閉じる
        // An empty body cannot be saved; close on the last saved content rather than trapping the user
        showFlash("error", t("memo.emptyBodyNotSaved"));
      } else if (!(await saveDetailEdit())) {
        const discard = await showConfirmModal(t("memo.discardUnsavedConfirm"));
        if (!discard) return;
      }
    }
    startMemoDetailCloseAnimation();
  }, [
    clearDetailAutoSaveTimer,
    detailEditAiResponse,
    detailHasUnsavedChanges,
    saveDetailEdit,
    showFlash,
    startMemoDetailCloseAnimation,
  ]);

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

  // 保存に失敗したまま回線が戻ったら、入力を待たずに保存し直す
  // Once the connection returns after a failed save, save again without waiting for more input
  useEffect(() => {
    if (detailSaveStatus !== "error" || !detailHasUnsavedChanges || !detailEditAiResponse.trim()) return;
    const retry = () => { void saveDetailEdit(); };
    window.addEventListener("online", retry);
    return () => window.removeEventListener("online", retry);
  }, [detailEditAiResponse, detailHasUnsavedChanges, detailSaveStatus, saveDetailEdit]);

  // 自動保存の待ち時間のうちにタブを離れる・閉じると入力が消えるので、その瞬間に保存を送る。
  // スマホではアプリ切り替えで pagehide が来ないことがあるため visibilitychange も見る。
  // Leaving or closing the tab inside the autosave delay would drop the input, so save at that
  // moment. Phones may skip pagehide on an app switch, hence visibilitychange as well.
  useEffect(() => {
    if (!selectedMemo || !detailHasUnsavedChanges) return;
    const flush = (event: Event) => {
      if (event.type === "visibilitychange" && document.visibilityState !== "hidden") return;
      clearDetailAutoSaveTimer();
      void saveDetailEdit({ keepalive: true });
    };
    document.addEventListener("visibilitychange", flush);
    window.addEventListener("pagehide", flush);
    return () => {
      document.removeEventListener("visibilitychange", flush);
      window.removeEventListener("pagehide", flush);
    };
  }, [clearDetailAutoSaveTimer, detailHasUnsavedChanges, saveDetailEdit, selectedMemo]);

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
    setDetailEditAiResponse: updateDetailBody,
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
