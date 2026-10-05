import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type Dispatch,
  type FormEvent,
  type SetStateAction,
} from "react";
import type { KeyedMutator } from "swr";

import { useTranslation } from "../../contexts/locale_context";
import { createMemo, suggestMemoTitle } from "../../lib/memo/api";
import { readMemoComposeDraft, writeMemoComposeDraft } from "../../lib/memo/compose_draft";
import type { FlashState, MemoComposeFormState, MemoListState } from "../../lib/memo/types";

type UseMemoPageComposerParams = {
  mutate: KeyedMutator<MemoListState>;
  showFlash: (type: FlashState["type"], text: string) => void;
  setFlashState: Dispatch<SetStateAction<FlashState | null>>;
};

// 新規メモ作成フォーム（クイックキャプチャ）の状態と操作
// State and actions for the new-memo composer (quick capture)
export function useMemoPageComposer({ mutate, showFlash, setFlashState }: UseMemoPageComposerParams) {
  const { t } = useTranslation();

  // Form state
  const [formState, setFormState] = useState<MemoComposeFormState>({
    ai_response: "",
    title: "",
    collection_id: null,
    background_color: null,
  });
  const [previewMode, setPreviewMode] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [aiSuggesting, setAiSuggesting] = useState(false);

  // Keep-style board state
  const [isComposeExpanded, setIsComposeExpanded] = useState(false);
  const [isComposePaletteOpen, setIsComposePaletteOpen] = useState(false);
  const composeTextareaRef = useRef<HTMLTextAreaElement | null>(null);

  // 書きかけを端末から復元し、以後の変更を控える。復元より先に空の初期値で上書きしないよう、
  // 読み込みが済むまで書き込みを止める。
  // Restore the unsaved memo from the device, then mirror later changes. Writing waits for the
  // read so the empty initial state cannot overwrite the stored draft first.
  const composeDraftLoadedRef = useRef(false);
  useEffect(() => {
    const draft = readMemoComposeDraft();
    composeDraftLoadedRef.current = true;
    if (draft) setFormState((prev) => ({ ...prev, ...draft }));
  }, []);
  useEffect(() => {
    if (!composeDraftLoadedRef.current) return;
    writeMemoComposeDraft(formState);
  }, [formState]);

  // 新規メモ作成用テキストエリアの高さを自動調整する副作用
  // Effect to automatically resize the textarea for new memo composition
  useEffect(() => {
    const el = composeTextareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    const next = Math.min(el.scrollHeight, 520);
    el.style.height = `${next}px`;
  }, [formState.ai_response, previewMode, isComposeExpanded]);

  // フォーム入力の変更ハンドラー。入力値をローカルステートに反映する
  // Form input change handler. Reflects input values into local state
  const handleFormChange = useCallback((event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => {
    const { name, value } = event.target;
    setFormState((prev) => ({
      ...prev,
      [name]: name === "collection_id" ? (value === "" ? null : Number(value)) : value,
    }));
  }, []);

  // メモの保存・更新を処理するハンドラー
  // Handler to process memo saving/updating
  const handleSubmitMemo = useCallback(async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setFlashState(null);
    if (!formState.ai_response.trim()) { showFlash("error", t("memo.bodyRequired")); return; }
    setSubmitting(true);
    try {
      await createMemo(formState, t("memo.memoSaveFailed"));
      setFormState({ ai_response: "", title: "", collection_id: null, background_color: null });
      setPreviewMode(false);
      setIsComposeExpanded(false);
      setIsComposePaletteOpen(false);
      showFlash("success", t("memo.memoSaved"));
      void mutate();
    } catch (error) {
      showFlash("error", error instanceof Error ? error.message : t("memo.memoSaveFailed"));
    } finally {
      setSubmitting(false);
    }
  }, [formState, mutate, setFlashState, showFlash]);

  // AIによる自動入力補完を実行するハンドラー
  // Handler to execute AI-based auto-completion for inputs
  const handleAiSuggest = useCallback(async () => {
    if (!formState.ai_response.trim()) { showFlash("error", t("memo.aiResponseRequired")); return; }
    setAiSuggesting(true);
    try {
      const payload = await suggestMemoTitle(formState.ai_response, t("memo.aiSuggestionFailed"));
      setFormState((prev) => ({
        ...prev,
        title: payload.title || prev.title,
      }));
      showFlash("success", t("memo.aiTitleSuggested"));
    } catch (error) {
      showFlash("error", error instanceof Error ? error.message : t("memo.aiSuggestionFailed"));
    } finally {
      setAiSuggesting(false);
    }
  }, [formState.ai_response, showFlash]);

  // 続きから書けるよう、カーソルは末尾に置く（チェックリストは挿入した「- [ ] 」の後ろになる）
  // Put the caret at the end so typing continues the text (after the inserted "- [ ] " for checklists)
  const focusComposeTextarea = useCallback(() => {
    window.setTimeout(() => {
      const textarea = composeTextareaRef.current;
      if (!textarea) return;
      textarea.focus();
      textarea.setSelectionRange(textarea.value.length, textarea.value.length);
    }, 0);
  }, []);

  const openTextComposer = useCallback(() => {
    setPreviewMode(false);
    setIsComposeExpanded(true);
    setIsComposePaletteOpen(false);
    focusComposeTextarea();
  }, [focusComposeTextarea]);

  const openChecklistComposer = useCallback(() => {
    setPreviewMode(false);
    setIsComposeExpanded(true);
    setIsComposePaletteOpen(false);
    setFormState((prev) => {
      const current = prev.ai_response;
      const nextChecklistLine = "- [ ] ";
      return {
        ...prev,
        title: prev.title || t("memo.checklist"),
        ai_response: current.trim()
          ? `${current.replace(/\s*$/u, "")}\n${nextChecklistLine}`
          : nextChecklistLine,
      };
    });
    focusComposeTextarea();
  }, [focusComposeTextarea]);

  const openComposePalette = useCallback(() => {
    setPreviewMode(false);
    setIsComposeExpanded(true);
    setIsComposePaletteOpen((open) => !open);
  }, []);

  const hasComposeDraft = Boolean(
    formState.ai_response.trim() ||
    formState.title.trim() ||
    formState.background_color,
  );
  const composeIsExpanded = isComposeExpanded || hasComposeDraft;

  return {
    formState,
    setFormState,
    previewMode,
    setPreviewMode,
    submitting,
    aiSuggesting,
    isComposePaletteOpen,
    setIsComposePaletteOpen,
    setIsComposeExpanded,
    composeTextareaRef,
    handleFormChange,
    handleSubmitMemo,
    handleAiSuggest,
    openTextComposer,
    openChecklistComposer,
    openComposePalette,
    hasComposeDraft,
    composeIsExpanded,
  };
}
