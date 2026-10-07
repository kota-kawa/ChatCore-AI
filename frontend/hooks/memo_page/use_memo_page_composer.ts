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
import type { EditorView } from "@codemirror/view";

import { useTranslation } from "../../contexts/locale_context";
import { createMemo, suggestMemoTitle } from "../../lib/memo/api";
import { readMemoComposeDraft, writeMemoComposeDraft } from "../../lib/memo/compose_draft";
import type { FlashState, MemoComposeFormState, MemoListState } from "../../lib/memo/types";

type UseMemoPageComposerParams = {
  // 書きかけの持ち主。サーバーが利用者を確認するまで、および未ログインでは null
  // Owner of the unsaved draft; null until the server confirms the user, and for guests
  draftOwnerId: string | null;
  mutate: KeyedMutator<MemoListState>;
  showFlash: (type: FlashState["type"], text: string) => void;
  setFlashState: Dispatch<SetStateAction<FlashState | null>>;
};

// 新規メモ作成フォーム（クイックキャプチャ）の状態と操作
// State and actions for the new-memo composer (quick capture)
export function useMemoPageComposer({ draftOwnerId, mutate, showFlash, setFlashState }: UseMemoPageComposerParams) {
  const { t } = useTranslation();

  // Form state
  const [formState, setFormState] = useState<MemoComposeFormState>({
    ai_response: "",
    title: "",
    collection_id: null,
    background_color: null,
  });
  const [sourceMode, setSourceMode] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [aiSuggesting, setAiSuggesting] = useState(false);

  // Keep-style board state
  const [isComposeExpanded, setIsComposeExpanded] = useState(false);
  const [isComposePaletteOpen, setIsComposePaletteOpen] = useState(false);
  const composeEditorRef = useRef<EditorView | null>(null);
  const [composeFocusRequest, setComposeFocusRequest] = useState(0);

  // 書きかけを端末から復元し、以後の変更を控える。持ち主が確認できるまでは読みも書きもしない。
  // 「読み込み済みの持ち主」は復元内容と同じ更新でまとめて反映されるので、書き込みは復元後の
  // 内容で初めて走り、空の初期値が控えを上書きすることはない。
  // Restore the unsaved memo from the device, then mirror later changes. Nothing is read or
  // written until the owner is confirmed. The "loaded for" owner is committed in the same update
  // as the restored content, so the first write already sees that content and the empty initial
  // state never overwrites the stored draft.
  const [composeDraftLoadedFor, setComposeDraftLoadedFor] = useState<string | null>(null);
  useEffect(() => {
    if (!draftOwnerId) {
      setComposeDraftLoadedFor(null);
      return;
    }
    const draft = readMemoComposeDraft(draftOwnerId);
    if (draft) setFormState((prev) => ({ ...prev, ...draft }));
    setComposeDraftLoadedFor(draftOwnerId);
  }, [draftOwnerId]);
  useEffect(() => {
    if (!draftOwnerId || composeDraftLoadedFor !== draftOwnerId) return;
    writeMemoComposeDraft(draftOwnerId, formState);
  }, [composeDraftLoadedFor, draftOwnerId, formState]);

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
      setSourceMode(false);
      setComposeFocusRequest(0);
      setIsComposeExpanded(false);
      setIsComposePaletteOpen(false);
      showFlash("success", t("memo.memoSaved"));
      void mutate();
    } catch (error) {
      showFlash("error", error instanceof Error ? error.message : t("memo.memoSaveFailed"));
    } finally {
      setSubmitting(false);
    }
  }, [formState, mutate, setFlashState, showFlash, t]);

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
  }, [formState.ai_response, showFlash, t]);

  // 続きから書けるよう、カーソルは末尾に置く（チェックリストは挿入した「- [ ] 」の後ろになる）
  // Put the caret at the end so typing continues the text (after the inserted "- [ ] " for checklists)
  const requestComposeFocus = useCallback(() => {
    setComposeFocusRequest((request) => request + 1);
  }, []);

  const openTextComposer = useCallback(() => {
    setSourceMode(false);
    setIsComposeExpanded(true);
    setIsComposePaletteOpen(false);
    requestComposeFocus();
  }, [requestComposeFocus]);

  const openChecklistComposer = useCallback(() => {
    setSourceMode(false);
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
    requestComposeFocus();
  }, [requestComposeFocus, t]);

  const openComposePalette = useCallback(() => {
    setComposeFocusRequest(0);
    setSourceMode(false);
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
    sourceMode,
    setSourceMode,
    submitting,
    aiSuggesting,
    isComposePaletteOpen,
    setIsComposePaletteOpen,
    setIsComposeExpanded,
    composeEditorRef,
    composeFocusRequest,
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
