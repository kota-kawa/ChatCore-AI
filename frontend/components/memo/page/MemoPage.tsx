import { SeoHead } from "../../SeoHead";
import { useTranslation } from "../../../contexts/locale_context";
import { useRouter } from "next/router";
import React, {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type DragEvent,
  type FormEvent,
} from "react";
import useSWR from "swr";

import "../../../scripts/core/csrf";
import { copyTextToClipboard } from "../../../scripts/chat/message_utils";
import { setLoggedInState } from "../../../scripts/core/app_state";
import {
  readCachedAuthState,
  releaseAuthBootAttribute,
  writeCachedAuthState,
} from "../../../scripts/core/auth_state_cache";
import { resilientFetch } from "../../../scripts/core/resilient_fetch";
import { showConfirmModal } from "../../../scripts/core/alert_modal";

import { MemoBulkBar } from "../MemoBulkBar";
import { MemoCollectionModal } from "../MemoCollectionModal";
import { MemoComposer } from "../MemoComposer";
import { MemoCrawlSummary } from "../MemoCrawlSummary";
import { MemoDetailModal } from "../MemoDetailModal";
import { MemoExportModal } from "../MemoExportModal";
import { MemoHistoryPanel } from "../MemoHistoryPanel";
import { MemoShareModal } from "../MemoShareModal";
import { MemoSidebar } from "../MemoSidebar";
import { MemoToolbar } from "../MemoToolbar";
import { MyContextPanel } from "../MyContextPanel";
import { MemoViewSwitcher, type MemoView } from "../MemoViewSwitcher";
import {
  loadCollections,
  loadMemoDetail,
  loadMemoList,
  memoFetchJsonOrThrow,
} from "../../../lib/memo/api";
import {
  DETAIL_AUTOSAVE_DELAY_MS,
  MEMO_DETAIL_CLOSE_ANIMATION_MS,
  memoPageDescription,
  memoStructuredData,
} from "../../../lib/memo/constants";
import {
  applySectionProjection,
  buildMemoListUrl,
  captureCardSnapshot,
  computeProjectedOrderFromSnapshot,
  getMemoActionMenuPosition,
  getMemoSectionKey,
  parseMemoText,
  setMemoDragImage,
} from "../../../lib/memo/utils";
import type {
  BulkAction,
  Collection,
  DetailSaveStatus,
  FlashState,
  FrozenRect,
  MemoActionMenuPosition,
  MemoDetail,
  MemoListState,
  MemoSummary,
  SharePayload,
} from "../../../lib/memo/types";

// MemoCrawlSummary はメモ画面の公開コンテンツとして別モジュールへ切り出した。
// 既存のテストとの互換性のためにこのモジュールから再エクスポートする。
// MemoCrawlSummary was extracted into its own module; re-export it here so that
// existing imports (and tests) referencing this page keep working.
export { MemoCrawlSummary };

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

// メモ機能のメインページコンポーネント
// Main page component for the memo feature
export default function MemoPage() {
  const { locale, t } = useTranslation();
  const router = useRouter();

  // Form state
  const [formState, setFormState] = useState({
    ai_response: "",
    title: "",
    collection_id: null as number | null,
    background_color: null as string | null,
  });
  const [previewMode, setPreviewMode] = useState(false);
  const [flashState, setFlashState] = useState<FlashState | null>(null);
  const flashTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [aiSuggesting, setAiSuggesting] = useState(false);
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  // 認証状態を表示に反映してよいか。キャッシュ反映済み、またはサーバー確認済みで true。
  // これが false の間は認証依存のUIをどちらも描画しない（誤った側を一瞬見せないため）。
  // Whether the auth state can drive the UI: true once the cache is applied or
  // the server has answered. While false, neither auth-dependent variant renders,
  // so the wrong one is never shown even for a frame.
  const [authUiReady, setAuthUiReady] = useState(false);

  // Filter/sort state
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [sortMode, setSortMode] = useState("manual");
  const [archiveScope, setArchiveScope] = useState("active");
  const [activeCollectionId, setActiveCollectionId] = useState<number | null>(null);
  // Notebook 画面内の表示切替。"memos" は従来のメモ、"context" はマイコンテキスト金庫。
  // View switch inside the notebook: "memos" is the classic memo list, "context" is the vault.
  const [activeView, setActiveView] = useState<MemoView>("memos");

  // Keep-style board state
  const [isComposeExpanded, setIsComposeExpanded] = useState(false);
  const [viewMode, setViewMode] = useState<"grid" | "list">("grid");
  const [isComposePaletteOpen, setIsComposePaletteOpen] = useState(false);

  // Toolbar search/filter section (collapsible on mobile)
  const [isFiltersOpen, setIsFiltersOpen] = useState(false);

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
  const [detailCopied, setDetailCopied] = useState(false);
  const [isMemoAgentOpen, setIsMemoAgentOpen] = useState(false);
  const detailAutoSaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const memoDetailCloseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const detailSaveSequenceRef = useRef(0);

  const [actionLoadingId, setActionLoadingId] = useState<string>("");

  // Share modal
  const [isShareModalOpen, setIsShareModalOpen] = useState(false);
  const [shareState, setShareState] = useState<SharePayload | null>(null);
  const [shareStatus, setShareStatus] = useState<FlashState | null>(null);
  const [shareLoading, setShareLoading] = useState(false);
  const [supportsNativeShare, setSupportsNativeShare] = useState(false);

  // Bulk selection
  const [isBulkMode, setIsBulkMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkCollectionId, setBulkCollectionId] = useState<number | null>(null);
  const [bulkLoading, setBulkLoading] = useState(false);

  // Collections sidebar
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [isCollectionPanelOpen, setIsCollectionPanelOpen] = useState(false);
  const [newCollectionName, setNewCollectionName] = useState("");
  const [newCollectionColor, setNewCollectionColor] = useState("#6b7280");
  const [collectionActionLoading, setCollectionActionLoading] = useState(false);
  const [editingCollectionId, setEditingCollectionId] = useState<number | null>(null);
  const [editingCollectionName, setEditingCollectionName] = useState("");
  const [editingCollectionColor, setEditingCollectionColor] = useState("#6b7280");

  // Memo item dropdown menu
  const [openMenuMemoId, setOpenMenuMemoId] = useState<string>("");
  const [menuPosition, setMenuPosition] = useState<MemoActionMenuPosition | null>(null);
  const [copiedMemoId, setCopiedMemoId] = useState<string>("");
  const [copyingMemoId, setCopyingMemoId] = useState<string>("");
  const [draggedMemoId, setDraggedMemoId] = useState<string>("");
  const [dragProjectedOrder, setDragProjectedOrder] = useState<string[] | null>(null);
  const [dragSaving, setDragSaving] = useState(false);
  const cardRefs = useRef<Map<string, HTMLElement>>(new Map());
  const cardPositionsRef = useRef<Map<string, DOMRect>>(new Map());
  const dragSnapshotRef = useRef<Map<string, FrozenRect>>(new Map());
  const dragScrollRef = useRef<{ x: number; y: number }>({ x: 0, y: 0 });
  const composeTextareaRef = useRef<HTMLTextAreaElement | null>(null);

  // Export modal
  const [isExportModalOpen, setIsExportModalOpen] = useState(false);
  const [exportFormat, setExportFormat] = useState<"markdown" | "json" | "csv">("markdown");
  const [exportScope, setExportScope] = useState<"all" | "selected">("all");
  const [exportSelectedIds, setExportSelectedIds] = useState<Set<string>>(new Set());

  // -----------------------------------------------------------------------
  // Data fetching
  // -----------------------------------------------------------------------

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQuery(query), 300);
    return () => window.clearTimeout(timer);
  }, [query]);

  const listUrl = useMemo(
    () => buildMemoListUrl({ query: debouncedQuery, sort: sortMode, archiveScope, collectionId: activeCollectionId }),
    [archiveScope, debouncedQuery, sortMode, activeCollectionId],
  );

  const { data: memoList = { memos: [], total: 0 }, error: memoLoadError, isLoading: memoListLoading, mutate } =
    useSWR<MemoListState>(listUrl, loadMemoList, { revalidateOnFocus: true, keepPreviousData: true, dedupingInterval: 3000 });

  const { data: collections = [], mutate: mutateCollections } =
    useSWR<Collection[]>(isLoggedIn ? "/memo/api/collections" : null, loadCollections, {
      revalidateOnFocus: false,
      dedupingInterval: 10000,
    });

  const memos = memoList.memos;
  const totalMemoCount = memoList.total;

  // While dragging, cards animate aside to preview the new order. The projection
  // is derived from a frozen geometry snapshot (see computeProjectedOrderFromSnapshot),
  // so the live reorder stays stable instead of oscillating.
  const displayMemos = useMemo(
    () => applySectionProjection(memos, dragProjectedOrder),
    [memos, dragProjectedOrder],
  );

  const { pinnedMemos, otherMemos } = useMemo(() => {
    const pinned: MemoSummary[] = [];
    const other: MemoSummary[] = [];
    for (const memo of displayMemos) {
      if (memo.is_pinned) pinned.push(memo);
      else other.push(memo);
    }
    return { pinnedMemos: pinned, otherMemos: other };
  }, [displayMemos]);

  const shareUrl = (shareState?.share_url || "").trim();
  const shareSnsLinks = useMemo(() => {
    if (!shareUrl) return { x: "#", line: "#", facebook: "#" };
    const eu = encodeURIComponent(shareUrl);
    const et = encodeURIComponent(t("memo.nativeShareText"));
    return {
      x: `https://twitter.com/intent/tweet?url=${eu}&text=${et}`,
      line: `https://social-plugins.line.me/lineit/share?url=${eu}`,
      facebook: `https://www.facebook.com/sharer/sharer.php?u=${eu}`,
    };
  }, [shareUrl, t]);

  // -----------------------------------------------------------------------
  // Effects
  // -----------------------------------------------------------------------

  // ページマウント時にカスタム要素の読み込みやボディのクラス設定を行う副作用
  // Effect to add body class and import custom elements on mount
  useEffect(() => {
    document.body.classList.add("memo-page");
    const importCustomElements = async () => {
      await Promise.all([import("../../../scripts/components/popup_menu"), import("../../../scripts/components/user_icon")]);
    };
    void importCustomElements();
    setSupportsNativeShare(typeof navigator !== "undefined" && typeof navigator.share === "function");
    return () => {
      document.body.classList.remove("memo-page");
      document.body.classList.remove("modal-open");
      if (flashTimerRef.current) {
        clearTimeout(flashTimerRef.current);
        flashTimerRef.current = null;
      }
      if (memoDetailCloseTimerRef.current) {
        clearTimeout(memoDetailCloseTimerRef.current);
        memoDetailCloseTimerRef.current = null;
      }
    };
  }, []);

  // モーダル開閉時にbody要素のスクロールを制御するクラスを切り替える副作用
  // Effect to toggle a body class controlling scroll when modals open/close
  useEffect(() => {
    const open = Boolean(selectedMemo) || isShareModalOpen || isCollectionPanelOpen || isExportModalOpen;
    document.body.classList.toggle("modal-open", open);
    return () => { document.body.classList.remove("modal-open"); };
  }, [isShareModalOpen, selectedMemo, isCollectionPanelOpen, isExportModalOpen]);

  // キャッシュ済みの認証状態を最初のペイント前に反映する。useEffect だと
  // 未ログインの初期stateが一度描画され、ログイン済みでもゲスト向けUIがちらつく。
  // 反映と同時にプリハイドレーション用のフラグを外し、以降はReactが表示を制御する。
  // Apply the cached auth state before the first paint. With a plain useEffect
  // the logged-out initial state gets painted once, flashing the guest UI at
  // signed-in users. Releasing the pre-hydration flag hands control to React.
  useLayoutEffect(() => {
    const cachedAuthState = readCachedAuthState();
    if (cachedAuthState !== null) {
      setIsLoggedIn(cachedAuthState);
      setLoggedInState(cachedAuthState);
      setAuthUiReady(true);
    }

    releaseAuthBootAttribute();
  }, []);

  // 認証状態の同期を行う副作用
  // Effect to synchronize the authentication state
  useEffect(() => {
    let cancelled = false;

    const syncAuthState = async () => {
      try {
        const res = await resilientFetch("/api/current_user", { credentials: "same-origin" });
        const data = res.ok ? await res.json() : { logged_in: false };
        const loggedIn = Boolean(data.logged_in);
        if (cancelled) return;
        setIsLoggedIn(loggedIn);
        setLoggedInState(loggedIn);
        writeCachedAuthState(loggedIn);
      } catch {
        if (cancelled) return;
        setIsLoggedIn(false);
        setLoggedInState(false);
      } finally {
        if (!cancelled) setAuthUiReady(true);
      }
    };
    void syncAuthState();

    return () => {
      cancelled = true;
    };
  }, []);

  // URLクエリパラメータから保存成功などのフラッシュメッセージを表示する副作用
  // Effect to show flash messages like save success from URL query parameters
  useEffect(() => {
    if (!router.isReady) return;
    if (router.query.saved !== "1") return;
    if (flashTimerRef.current) clearTimeout(flashTimerRef.current);
    setFlashState({ type: "success", text: t("memo.memoSaved") });
    flashTimerRef.current = setTimeout(() => {
      setFlashState(null);
      flashTimerRef.current = null;
    }, 4000);
    const nextQuery = { ...router.query };
    delete nextQuery.saved;
    void router.replace({ pathname: router.pathname, query: nextQuery }, undefined, { shallow: true });
  }, [router, router.isReady, router.pathname, router.query]);

  // 新規メモ作成用テキストエリアの高さを自動調整する副作用
  // Effect to automatically resize the textarea for new memo composition
  useEffect(() => {
    const el = composeTextareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    const next = Math.min(el.scrollHeight, 520);
    el.style.height = `${next}px`;
  }, [formState.ai_response, previewMode, isComposeExpanded]);

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

  // メモアクションメニュー外のクリックやスクロールでメニューを閉じる副作用
  // Effect to close the memo action menu on outside click or scroll
  useEffect(() => {
    if (!openMenuMemoId) return;
    const onDown = (e: MouseEvent) => {
      const target = e.target as Element;
      if (!target.closest?.(".memo-item__menu-wrap") && !target.closest?.(".memo-item__dropdown")) {
        setOpenMenuMemoId("");
        setMenuPosition(null);
      }
    };
    const onScrollOrResize = () => {
      setOpenMenuMemoId("");
      setMenuPosition(null);
    };
    document.addEventListener("mousedown", onDown);
    window.addEventListener("scroll", onScrollOrResize, true);
    window.addEventListener("resize", onScrollOrResize);
    return () => {
      document.removeEventListener("mousedown", onDown);
      window.removeEventListener("scroll", onScrollOrResize, true);
      window.removeEventListener("resize", onScrollOrResize);
    };
  }, [openMenuMemoId]);

  // Exit bulk mode when memos change drastically
  useEffect(() => {
    if (!isBulkMode) return;
    setSelectedIds((prev) => {
      const memoIdSet = new Set(memos.map((m) => String(m.id)));
      const next = new Set([...prev].filter((id) => memoIdSet.has(id)));
      return next.size === prev.size ? prev : next;
    });
  }, [memos, isBulkMode]);

  useEffect(() => {
    if (!isExportModalOpen) return;
    setExportSelectedIds((prev) => {
      const memoIdSet = new Set(memos.map((m) => String(m.id)));
      const next = new Set([...prev].filter((id) => memoIdSet.has(id)));
      return next.size === prev.size ? prev : next;
    });
  }, [isExportModalOpen, memos]);

  // -----------------------------------------------------------------------
  // Helpers
  // -----------------------------------------------------------------------

  const showFlash = useCallback((type: "success" | "error", text: string) => {
    if (flashTimerRef.current) clearTimeout(flashTimerRef.current);
    setFlashState({ type, text });
    flashTimerRef.current = setTimeout(() => {
      setFlashState(null);
      flashTimerRef.current = null;
    }, 4000);
  }, []);

  const canDragMemos =
    archiveScope === "active" &&
    !isBulkMode &&
    !dragSaving &&
    sortMode === "manual" &&
    !query.trim();
  const canReorderCurrentView =
    canDragMemos;

  // フォーム入力の変更ハンドラー。入力値をローカルステートに反映する
  // Form input change handler. Reflects input values into local state
  const handleFormChange = useCallback((event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => {
    const { name, value } = event.target;
    setFormState((prev) => ({
      ...prev,
      [name]: name === "collection_id" ? (value === "" ? null : Number(value)) : value,
    }));
  }, []);

  const withActionLoading = useCallback(async (memoId: string | number, action: () => Promise<void>) => {
    const id = String(memoId);
    setActionLoadingId(id);
    try { await action(); } finally { setActionLoadingId(""); }
  }, []);

  const shouldKeepMemoInCurrentList = useCallback((memo: MemoSummary) => {
    if (archiveScope === "active" && memo.is_archived) return false;
    if (archiveScope === "archived" && !memo.is_archived) return false;
    if (activeCollectionId !== null && memo.collection_id !== activeCollectionId) return false;
    return true;
  }, [activeCollectionId, archiveScope]);

  const updateMemoListOptimistically = useCallback(
    async (updater: (memo: MemoSummary) => MemoSummary | null, targetIds: Iterable<string | number>) => {
      const targets = new Set(Array.from(targetIds, String));
      await mutate((current) => {
        if (!current) return current;
        let changed = false;
        const nextMemos: MemoSummary[] = [];

        current.memos.forEach((memo) => {
          if (!targets.has(String(memo.id))) {
            nextMemos.push(memo);
            return;
          }

          changed = true;
          const nextMemo = updater(memo);
          if (nextMemo && shouldKeepMemoInCurrentList(nextMemo)) {
            nextMemos.push(nextMemo);
          }
        });

        if (!changed) return current;
        return {
          ...current,
          memos: nextMemos,
          total: Math.max(0, current.total + nextMemos.length - current.memos.length),
        };
      }, { revalidate: false });
    },
    [mutate, shouldKeepMemoInCurrentList],
  );

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

  // -----------------------------------------------------------------------
  // Submit / AI suggest
  // -----------------------------------------------------------------------

  // メモの保存・更新を処理するハンドラー
  // Handler to process memo saving/updating
  const handleSubmitMemo = useCallback(async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setFlashState(null);
    if (!formState.ai_response.trim()) { showFlash("error", t("memo.bodyRequired")); return; }
    setSubmitting(true);
    try {
      await memoFetchJsonOrThrow(
        "/memo/api",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify(formState),
        },
        { defaultMessage: t("memo.memoSaveFailed") },
      );
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
  }, [formState, mutate, showFlash]);

  // AIによる自動入力補完を実行するハンドラー
  // Handler to execute AI-based auto-completion for inputs
  const handleAiSuggest = useCallback(async () => {
    if (!formState.ai_response.trim()) { showFlash("error", t("memo.aiResponseRequired")); return; }
    setAiSuggesting(true);
    try {
      const { payload } = await memoFetchJsonOrThrow<{ title?: string }>(
        "/memo/api/suggest",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ ai_response: formState.ai_response }),
        },
        { defaultMessage: t("memo.aiSuggestionFailed") },
      );
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

  const focusComposeTextarea = useCallback(() => {
    window.setTimeout(() => {
      composeTextareaRef.current?.focus();
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

  // -----------------------------------------------------------------------
  // Memo detail
  // -----------------------------------------------------------------------

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
      const body: Record<string, unknown> = {
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

      const { payload } = await memoFetchJsonOrThrow<{ memo?: MemoDetail }>(
        `/memo/api/${selectedMemo.id}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify(body),
        },
        { defaultMessage: t("memo.memoUpdateFailed"), hasApplicationError: (data) => !data.memo },
      );
      if (requestId === detailSaveSequenceRef.current) {
        if (payload.memo) {
          // Keep the exact text the user submitted as the saved baseline
          // instead of the server's normalized response. This prevents the
          // autosave from rewriting what the user is actively editing (for
          // example, a leading blank line they just added), so the editor
          // only ever changes in response to the user's own input.
          setSelectedMemo({
            ...payload.memo,
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
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (isExportModalOpen) { setIsExportModalOpen(false); return; }
      if (isCollectionPanelOpen) { setIsCollectionPanelOpen(false); return; }
      if (isShareModalOpen) { setIsShareModalOpen(false); return; }
      if (selectedMemo) void closeMemoDetail();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => { document.removeEventListener("keydown", onKeyDown); };
  }, [closeMemoDetail, isShareModalOpen, selectedMemo, isCollectionPanelOpen, isExportModalOpen]);

  useEffect(() => {
    if (!selectedMemo) setIsMemoAgentOpen(false);
  }, [selectedMemo]);

  // -----------------------------------------------------------------------
  // Pin / Archive / Delete
  // -----------------------------------------------------------------------

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
        await memoFetchJsonOrThrow(
          `/memo/api/${memo.id}/pin`,
          { method: "POST", headers: { "Content-Type": "application/json" }, credentials: "same-origin", body: JSON.stringify({ enabled }) },
          { defaultMessage: t("memo.pinUpdateFailed") },
        );
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
        await memoFetchJsonOrThrow(
          `/memo/api/${memo.id}/archive`,
          { method: "POST", headers: { "Content-Type": "application/json" }, credentials: "same-origin", body: JSON.stringify({ enabled }) },
          { defaultMessage: t("memo.archiveUpdateFailed") },
        );
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
        await memoFetchJsonOrThrow(
          `/memo/api/${memo.id}`,
          { method: "DELETE", credentials: "same-origin" },
          { defaultMessage: t("memo.memoDeleteFailed") },
        );
        showFlash("success", t("memo.memoDeleted"));
        if (selectedMemo?.id && String(selectedMemo.id) === String(memo.id)) startMemoDetailCloseAnimation();
        await mutate();
      } catch (error) {
        showFlash("error", error instanceof Error ? error.message : t("memo.memoDeleteFailed"));
        await mutate();
      }
    });
  }, [mutate, selectedMemo?.id, showFlash, startMemoDetailCloseAnimation, updateMemoListOptimistically, withActionLoading]);

  const copyMemoFullText = useCallback(async (memo: MemoSummary) => {
    const memoId = String(memo.id);
    setCopyingMemoId(memoId);
    try {
      const detail = await loadMemoDetail(memo.id);
      const fullText = detail?.ai_response || memo.excerpt || "";
      const content = `${detail?.title || memo.title || t("memo.savedMemo")}\n\n${parseMemoText(fullText)}`;
      await copyTextToClipboard(content.trim());
      setCopiedMemoId(memoId);
      setTimeout(() => {
        setCopiedMemoId((current) => (current === memoId ? "" : current));
      }, 1400);
    } catch (error) { showFlash("error", error instanceof Error ? error.message : t("memo.copyFailed")); }
    finally { setCopyingMemoId(""); }
  }, [showFlash]);

  const copyDetailFullText = useCallback(async () => {
    const fullText = detailEditAiResponse || selectedMemo?.ai_response || "";
    const content = `${detailEditTitle || selectedMemo?.title || t("memo.savedMemo")}\n\n${parseMemoText(fullText)}`;
    try {
      await copyTextToClipboard(content.trim());
      setDetailCopied(true);
      setTimeout(() => setDetailCopied(false), 1400);
    } catch (error) { showFlash("error", error instanceof Error ? error.message : t("memo.copyFailed")); }
  }, [detailEditAiResponse, detailEditTitle, selectedMemo?.ai_response, selectedMemo?.title, showFlash]);

  const toggleMemoActionMenu = useCallback((memoId: string, trigger: HTMLElement) => {
    if (openMenuMemoId === memoId) {
      setOpenMenuMemoId("");
      setMenuPosition(null);
      return;
    }
    setMenuPosition(getMemoActionMenuPosition(trigger));
    setOpenMenuMemoId(memoId);
  }, [openMenuMemoId]);

  const clearMemoDragState = useCallback(() => {
    setDraggedMemoId("");
    setDragProjectedOrder(null);
    dragSnapshotRef.current = new Map();
  }, []);

  // メモのドラッグ開始時のハンドラー
  // Handler when starting to drag a memo
  const handleMemoDragStart = useCallback((event: DragEvent<HTMLElement>, memo: MemoSummary) => {
    if (!canDragMemos) {
      event.preventDefault();
      return;
    }
    const memoId = String(memo.id);
    setOpenMenuMemoId("");
    setMenuPosition(null);
    setDraggedMemoId(memoId);
    setDragProjectedOrder(null);
    // Freeze the current card geometry; every dragover hit-test resolves against
    // this snapshot so live column reflow can't perturb the targeting.
    dragSnapshotRef.current = captureCardSnapshot(cardRefs.current);
    dragScrollRef.current = { x: window.scrollX, y: window.scrollY };
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", memoId);
    setMemoDragImage(event);
  }, [canDragMemos]);

  // メモをドラッグ中のリスト上の判定処理
  // Handler for drag-over events on the memo list to determine drop targets
  const handleMemoSectionDragOver = useCallback((event: DragEvent<HTMLUListElement>, sectionMemos: MemoSummary[]) => {
    if (!canReorderCurrentView || !draggedMemoId || sectionMemos.length === 0) return;
    const draggedMemo = memos.find((memo) => String(memo.id) === draggedMemoId);
    if (!draggedMemo || getMemoSectionKey(draggedMemo) !== getMemoSectionKey(sectionMemos[0])) return;

    event.preventDefault();
    event.dataTransfer.dropEffect = "move";

    // Map the pointer back into the snapshot's coordinate space, accounting for
    // any page scroll that happened since the drag began.
    const pointerX = event.clientX + (window.scrollX - dragScrollRef.current.x);
    const pointerY = event.clientY + (window.scrollY - dragScrollRef.current.y);
    const order = computeProjectedOrderFromSnapshot(
      memos,
      draggedMemoId,
      pointerX,
      pointerY,
      dragSnapshotRef.current,
    );
    if (!order) return;
    setDragProjectedOrder((prev) => {
      if (prev && prev.length === order.length && prev.every((id, i) => id === order[i])) {
        return prev;
      }
      return order;
    });
  }, [canReorderCurrentView, memos, draggedMemoId]);

  // ドラッグ＆ドロップ完了時の処理。並び順の更新を行う
  // Handler for dropping a memo. Updates the order of memos
  const handleMemoDrop = useCallback(async (event: DragEvent<HTMLElement>) => {
    event.preventDefault();
    const sourceId = draggedMemoId || event.dataTransfer.getData("text/plain");
    const projection = dragProjectedOrder;

    if (!canReorderCurrentView || !sourceId || !projection) {
      clearMemoDragState();
      return;
    }

    const movedIdx = projection.findIndex((id) => id === sourceId);
    if (movedIdx < 0) {
      clearMemoDragState();
      return;
    }

    const memoId = Number(sourceId);
    const beforeId = movedIdx > 0 ? Number(projection[movedIdx - 1]) : null;
    const afterId = movedIdx < projection.length - 1 ? Number(projection[movedIdx + 1]) : null;
    if (!Number.isFinite(memoId) || (beforeId !== null && !Number.isFinite(beforeId)) || (afterId !== null && !Number.isFinite(afterId))) {
      showFlash("error", t("memo.invalidReorderId"));
      clearMemoDragState();
      return;
    }

    setDragSaving(true);
    await mutate((current) => {
      if (!current) return current;
      const next = applySectionProjection(current.memos, projection);
      return { ...current, memos: next };
    }, { revalidate: false });
    clearMemoDragState();

    try {
      await memoFetchJsonOrThrow(
        "/memo/api/reorder",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ memo_id: memoId, before_id: beforeId, after_id: afterId }),
        },
        { defaultMessage: t("memo.reorderFailed") },
      );
      await mutate();
    } catch (error) {
      showFlash("error", error instanceof Error ? error.message : t("memo.reorderFailed"));
      await mutate();
    } finally {
      setDragSaving(false);
    }
  }, [
    canReorderCurrentView,
    clearMemoDragState,
    dragProjectedOrder,
    draggedMemoId,
    mutate,
    showFlash,
  ]);

  // FLIP: animate cards smoothly to their new positions after a reorder.
  useLayoutEffect(() => {
    const prevPositions = cardPositionsRef.current;
    const nextPositions = new Map<string, DOMRect>();
    cardRefs.current.forEach((el, id) => {
      if (el && el.isConnected) nextPositions.set(id, el.getBoundingClientRect());
    });
    nextPositions.forEach((nextRect, id) => {
      if (id === draggedMemoId) return;
      const prevRect = prevPositions.get(id);
      if (!prevRect) return;
      const dx = prevRect.left - nextRect.left;
      const dy = prevRect.top - nextRect.top;
      if (Math.abs(dx) < 1 && Math.abs(dy) < 1) return;
      const el = cardRefs.current.get(id);
      if (!el) return;
      el.style.transition = "none";
      el.style.transform = `translate(${dx}px, ${dy}px)`;
      void el.offsetWidth;
      el.style.transition = "";
      el.style.transform = "";
    });
    cardPositionsRef.current = nextPositions;
  }, [displayMemos, draggedMemoId]);

  // -----------------------------------------------------------------------
  // Bulk operations
  // -----------------------------------------------------------------------

  const toggleSelectMemo = useCallback((memoId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(memoId)) next.delete(memoId);
      else next.add(memoId);
      return next;
    });
  }, []);

  const selectAll = useCallback(() => {
    setSelectedIds(new Set(memos.map((m) => String(m.id))));
  }, [memos]);

  const deselectAll = useCallback(() => {
    setSelectedIds(new Set());
  }, []);

  const toggleExportMemo = useCallback((memoId: string) => {
    setExportSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(memoId)) next.delete(memoId);
      else next.add(memoId);
      return next;
    });
    setExportScope("selected");
  }, []);

  const selectAllExportMemos = useCallback(() => {
    setExportSelectedIds(new Set(memos.map((memo) => String(memo.id))));
    setExportScope("selected");
  }, [memos]);

  const clearExportSelection = useCallback(() => {
    setExportSelectedIds(new Set());
  }, []);

  const executeBulkAction = useCallback(async (action: BulkAction, extra?: { collectionId?: number | null }) => {
    if (selectedIds.size === 0) return;
    const selectedIdList = Array.from(selectedIds);
    setBulkLoading(true);

    const now = new Date().toISOString();
    const targetCollection =
      extra?.collectionId !== undefined && extra.collectionId !== null
        ? collections.find((collection) => collection.id === extra.collectionId) ?? null
        : null;

    await updateMemoListOptimistically((memo) => {
      if (action === "delete") return null;
      if (action === "archive") return { ...memo, is_archived: true, archived_at: now };
      if (action === "unarchive") return { ...memo, is_archived: false, archived_at: null };
      if (action === "pin") return { ...memo, is_pinned: true, pinned_at: now };
      if (action === "unpin") return { ...memo, is_pinned: false, pinned_at: null };
      if (action === "set_collection" && targetCollection) {
        return {
          ...memo,
          collection_id: targetCollection.id,
          collection_name: targetCollection.name,
          collection_color: targetCollection.color,
        };
      }
      if (action === "clear_collection") {
        return {
          ...memo,
          collection_id: null,
          collection_name: null,
          collection_color: null,
        };
      }
      return memo;
    }, selectedIdList);

    try {
      const body: Record<string, unknown> = {
        action,
        memo_ids: selectedIdList.map(Number),
      };
      if (extra?.collectionId !== undefined) body.collection_id = extra.collectionId;

      await memoFetchJsonOrThrow(
        "/memo/api/bulk",
        { method: "POST", headers: { "Content-Type": "application/json" }, credentials: "same-origin", body: JSON.stringify(body) },
        { defaultMessage: t("memo.bulkActionFailed") },
      );
      const labels: Record<BulkAction, string> = {
        delete: t("common.delete"), archive: t("memo.archive"), unarchive: t("memo.unarchive"),
        pin: t("memo.pin"), unpin: t("memo.unpin"),
        set_collection: t("memo.setCollection"), clear_collection: t("memo.clearCollection"),
      };
      showFlash("success", t("memo.bulkActionSuccess", { count: selectedIds.size, action: labels[action] }));
      if (action === "delete") setSelectedIds(new Set());
      await mutate();
      setBulkCollectionId(null);
    } catch (error) {
      showFlash("error", error instanceof Error ? error.message : t("memo.bulkActionFailed"));
      await mutate();
    } finally {
      setBulkLoading(false);
    }
  }, [collections, mutate, selectedIds, showFlash, updateMemoListOptimistically]);

  const exitBulkMode = useCallback(() => {
    setIsBulkMode(false);
    setSelectedIds(new Set());
  }, []);

  // -----------------------------------------------------------------------
  // Share modal
  // -----------------------------------------------------------------------

  const loadShareState = useCallback(async (memoId: string | number) => {
    const { payload } = await memoFetchJsonOrThrow<SharePayload>(
      `/memo/api/${memoId}/share`,
      { credentials: "same-origin" },
      { defaultMessage: t("memo.shareInfoFailed") },
    );
    setShareState(payload);
    return payload;
  }, []);

  const openShareModal = useCallback(async (memo: MemoSummary) => {
    const memoId = String(memo.id || "");
    if (!memoId) { showFlash("error", t("memo.shareTargetMissing")); return; }
    setIsShareModalOpen(true);
    setShareState(null);
    setShareStatus({ type: "success", text: t("memo.loadingShareInfo") });
    setShareLoading(true);
    try {
      const payload = await loadShareState(memoId);
      if (payload.share_url && payload.is_active) {
        setShareStatus({ type: "success", text: t("memo.showingShareLink") });
        return;
      }

      setShareStatus({ type: "success", text: t("memo.creatingShareLink") });
      const { payload: createdPayload } = await memoFetchJsonOrThrow<SharePayload>(
        `/memo/api/${memoId}/share`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ force_refresh: false, expires_in_days: 30 }),
        },
        { defaultMessage: t("memo.createShareLinkFailed") },
      );
      setShareState(createdPayload);
      setShareStatus({ type: "success", text: t("memo.shareLinkCreated") });
      await mutate();
    } catch (error) {
      setShareStatus({ type: "error", text: error instanceof Error ? error.message : t("memo.shareInfoFailed") });
    } finally {
      setShareLoading(false);
    }
  }, [loadShareState, mutate, showFlash]);

  const closeShareModal = useCallback(() => {
    setIsShareModalOpen(false);
    setShareStatus(null);
    setShareState(null);
  }, []);

  const copyShareLink = useCallback(async () => {
    if (!shareUrl) { setShareStatus({ type: "error", text: t("memo.createShareLinkFirst") }); return; }
    try {
      await copyTextToClipboard(shareUrl);
      setShareStatus({ type: "success", text: t("memo.shareLinkCopied") });
    } catch (error) {
      setShareStatus({ type: "error", text: error instanceof Error ? error.message : t("memo.copyLinkFailed") });
    }
  }, [shareUrl]);

  const openNativeShareSheet = useCallback(async () => {
    if (!shareUrl) { setShareStatus({ type: "error", text: t("memo.createShareLinkFirst") }); return; }
    if (!supportsNativeShare || typeof navigator.share !== "function") { setShareStatus({ type: "error", text: t("memo.nativeShareUnsupported") }); return; }
    try {
      await navigator.share({ title: t("memo.nativeShareTitle"), text: t("memo.nativeShareText"), url: shareUrl });
    } catch (error) {
      if (error instanceof Error && error.name === "AbortError") return;
      setShareStatus({ type: "error", text: error instanceof Error ? error.message : t("memo.nativeShareFailed") });
    }
  }, [shareUrl, supportsNativeShare]);

  // -----------------------------------------------------------------------
  // Collections management
  // -----------------------------------------------------------------------

  // 新しいコレクションを作成するハンドラー
  // Handler to create a new collection
  const handleCreateCollection = useCallback(async () => {
    const name = newCollectionName.trim();
    if (!name) { showFlash("error", t("memo.collectionNameRequired")); return; }
    setCollectionActionLoading(true);
    try {
      await memoFetchJsonOrThrow(
        "/memo/api/collections",
        { method: "POST", headers: { "Content-Type": "application/json" }, credentials: "same-origin", body: JSON.stringify({ name, color: newCollectionColor }) },
        { defaultMessage: t("memo.collectionCreateFailed") },
      );
      setNewCollectionName("");
      setNewCollectionColor("#6b7280");
      showFlash("success", t("memo.collectionCreated"));
      await mutateCollections();
    } catch (error) { showFlash("error", error instanceof Error ? error.message : t("memo.collectionCreateFailed")); }
    finally { setCollectionActionLoading(false); }
  }, [newCollectionColor, newCollectionName, mutateCollections, showFlash]);

  // 既存のコレクションを更新するハンドラー
  // Handler to update an existing collection
  const handleUpdateCollection = useCallback(async (collectionId: number) => {
    setCollectionActionLoading(true);
    try {
      await memoFetchJsonOrThrow(
        `/memo/api/collections/${collectionId}`,
        { method: "PATCH", headers: { "Content-Type": "application/json" }, credentials: "same-origin", body: JSON.stringify({ name: editingCollectionName, color: editingCollectionColor }) },
        { defaultMessage: t("memo.collectionUpdateFailed") },
      );
      setEditingCollectionId(null);
      showFlash("success", t("memo.collectionUpdated"));
      await mutateCollections();
      await mutate();
    } catch (error) { showFlash("error", error instanceof Error ? error.message : t("memo.collectionUpdateFailed")); }
    finally { setCollectionActionLoading(false); }
  }, [editingCollectionColor, editingCollectionName, mutate, mutateCollections, showFlash]);

  // コレクションを削除するハンドラー
  // Handler to delete a collection
  const handleDeleteCollection = useCallback(async (collectionId: number, name: string) => {
    const confirmed = await showConfirmModal(t("memo.collectionDeleteConfirm", { name }));
    if (!confirmed) return;
    setCollectionActionLoading(true);
    try {
      await memoFetchJsonOrThrow(
        `/memo/api/collections/${collectionId}`,
        { method: "DELETE", credentials: "same-origin" },
        { defaultMessage: t("memo.collectionDeleteFailed") },
      );
      if (activeCollectionId === collectionId) setActiveCollectionId(null);
      showFlash("success", t("memo.collectionDeleted"));
      await mutateCollections();
      await mutate();
    } catch (error) { showFlash("error", error instanceof Error ? error.message : t("memo.collectionDeleteFailed")); }
    finally { setCollectionActionLoading(false); }
  }, [activeCollectionId, mutate, mutateCollections, showFlash]);

  // -----------------------------------------------------------------------
  // Export
  // -----------------------------------------------------------------------

  // メモをJSON形式でエクスポートするハンドラー
  // Handler to export memos in JSON format
  const handleExport = useCallback(() => {
    if (exportScope === "selected" && exportSelectedIds.size === 0) {
      showFlash("error", t("memo.exportSelectionRequired"));
      return;
    }
    const ids = exportScope === "selected"
      ? Array.from(exportSelectedIds).join(",")
      : "";
    const params = new URLSearchParams({ format: exportFormat });
    if (ids) params.set("ids", ids);
    const url = `/memo/api/export?${params.toString()}`;
    const a = document.createElement("a");
    a.href = url;
    a.download = `memos.${exportFormat === "json" ? "json" : exportFormat === "csv" ? "csv" : "md"}`;
    a.click();
    setIsExportModalOpen(false);
    showFlash("success", t("memo.exportStarted"));
  }, [exportFormat, exportScope, exportSelectedIds, showFlash]);

  // -----------------------------------------------------------------------
  // Render
  // -----------------------------------------------------------------------

  const hasSelection = selectedIds.size > 0;
  const exportSelectedCount = exportSelectedIds.size;
  const visibleExportIds = memos.map((memo) => String(memo.id));
  const allVisibleExportSelected = visibleExportIds.length > 0 && visibleExportIds.every((id) => exportSelectedIds.has(id));
  const canDownloadExport = exportScope === "all" || exportSelectedCount > 0;
  const activeCollection = activeCollectionId !== null ? collections.find((c) => c.id === activeCollectionId) : null;
  const hasActiveFilters = Boolean(query.trim()) || sortMode !== "manual" || archiveScope !== "active" || activeCollectionId !== null;
  const hasComposeDraft = Boolean(
    formState.ai_response.trim() ||
    formState.title.trim() ||
    formState.background_color,
  );
  const composeIsExpanded = isComposeExpanded || hasComposeDraft;

  return (
    <>
      <SeoHead
        title={t("memo.title")}
        description={locale === "en" ? "Save, organize, search, and share your notes and useful AI responses." : memoPageDescription}
        canonicalPath="/memo"
        structuredData={memoStructuredData}
      />

      <div className="memo-page-shell cc-page-rise">
        {/* 検索エンジン・支援技術向けの説明的なページ見出し（視覚的には非表示） */}
        {/* Descriptive page heading for search engines and assistive tech (visually hidden) */}
        <h1 className="sr-only">{locale === "en" ? "Chat Core Memos — save, organize, and share useful knowledge" : "Chat Core メモ ― AIの回答や作業メモを保存・整理・共有"}</h1>
        <action-menu></action-menu>

        <div
          id="auth-buttons"
          style={{
            display: authUiReady && !isLoggedIn ? "" : "none",
            position: "fixed",
            top: 10,
            right: 10,
            zIndex: "var(--z-floating-controls, 65)",
          }}
        >
          <button type="button" id="login-btn" className="auth-btn" onClick={() => { window.location.href = "/login"; }}>
            <i className="bi bi-person-circle"></i>
            <span>{locale === "en" ? "Log in / Sign up" : "ログイン / 登録"}</span>
          </button>
        </div>

        <user-icon id="userIcon" style={authUiReady && isLoggedIn ? undefined : { display: "none" }}></user-icon>

        <div className={`memo-layout${isSidebarCollapsed ? " is-sidebar-collapsed" : ""}`}>
          <MemoSidebar
            isSidebarCollapsed={isSidebarCollapsed}
            setIsSidebarCollapsed={setIsSidebarCollapsed}
            activeCollectionId={activeCollectionId}
            setActiveCollectionId={setActiveCollectionId}
            archiveScope={archiveScope}
            setArchiveScope={setArchiveScope}
            sortMode={sortMode}
            setSortMode={setSortMode}
            collections={collections}
            setIsCollectionPanelOpen={setIsCollectionPanelOpen}
            activeView={activeView}
            setActiveView={setActiveView}
          />

          <div className="memo-container">
            <MemoViewSwitcher activeView={activeView} setActiveView={setActiveView} />
            {activeView === "context" ? (
            <MyContextPanel isLoggedIn={isLoggedIn} />
            ) : (
            <>
            {/* 未ログイン時のみ表示する機能紹介テキスト（クロール可能な公開コンテンツを確保する） */}
            {/* Short feature intro shown only when logged out (provides crawlable public content) */}
            {!isLoggedIn && (
              <p className="memo-guest-intro">{t("memo.guestIntro")}</p>
            )}
            {/* ── Toolbar ── */}
            <MemoToolbar
              activeCollection={activeCollection}
              activeCollectionId={activeCollectionId}
              archiveScope={archiveScope}
              sortMode={sortMode}
              collections={collections}
              totalMemoCount={totalMemoCount}
              query={query}
              setQuery={setQuery}
              hasActiveFilters={hasActiveFilters}
              setArchiveScope={setArchiveScope}
              setSortMode={setSortMode}
              setActiveCollectionId={setActiveCollectionId}
              viewMode={viewMode}
              setViewMode={setViewMode}
              isBulkMode={isBulkMode}
              exitBulkMode={exitBulkMode}
              setIsBulkMode={setIsBulkMode}
              setIsExportModalOpen={setIsExportModalOpen}
              isFiltersOpen={isFiltersOpen}
              setIsFiltersOpen={setIsFiltersOpen}
              setIsCollectionPanelOpen={setIsCollectionPanelOpen}
            />

          {flashState && (
            <div className={`memo-flash memo-flash--${flashState.type}`} role="alert">
              {flashState.text}
            </div>
          )}

          <MemoCrawlSummary />

          {/* Bulk action bar */}
          {isBulkMode && (
            <MemoBulkBar
              hasSelection={hasSelection}
              selectedIds={selectedIds}
              memos={memos}
              selectAll={selectAll}
              deselectAll={deselectAll}
              executeBulkAction={executeBulkAction}
              bulkLoading={bulkLoading}
              collections={collections}
              bulkCollectionId={bulkCollectionId}
              setBulkCollectionId={setBulkCollectionId}
            />
          )}

          {/* ── Quick capture ── */}
          <MemoComposer
            composeIsExpanded={composeIsExpanded}
            openTextComposer={openTextComposer}
            openChecklistComposer={openChecklistComposer}
            openComposePalette={openComposePalette}
            handleSubmitMemo={handleSubmitMemo}
            formState={formState}
            handleFormChange={handleFormChange}
            previewMode={previewMode}
            setPreviewMode={setPreviewMode}
            composeTextareaRef={composeTextareaRef}
            collections={collections}
            setFormState={setFormState}
            aiSuggesting={aiSuggesting}
            handleAiSuggest={handleAiSuggest}
            isComposePaletteOpen={isComposePaletteOpen}
            submitting={submitting}
            setIsComposeExpanded={setIsComposeExpanded}
            setIsComposePaletteOpen={setIsComposePaletteOpen}
            hasComposeDraft={hasComposeDraft}
          />

          <div className={`memo-board memo-board--${viewMode}`}>
            {/* ── Memo list ── */}
            <MemoHistoryPanel
              activeCollection={activeCollection}
              totalMemoCount={totalMemoCount}
              memoLoadError={memoLoadError}
              memoListLoading={memoListLoading}
              memos={memos}
              pinnedMemos={pinnedMemos}
              otherMemos={otherMemos}
              openMenuMemoId={openMenuMemoId}
              actionLoadingId={actionLoadingId}
              selectedIds={selectedIds}
              copiedMemoId={copiedMemoId}
              copyingMemoId={copyingMemoId}
              canDragMemos={canDragMemos}
              draggedMemoId={draggedMemoId}
              cardRefs={cardRefs}
              isBulkMode={isBulkMode}
              menuPosition={menuPosition}
              canReorderCurrentView={canReorderCurrentView}
              handleMemoDragStart={handleMemoDragStart}
              clearMemoDragState={clearMemoDragState}
              toggleSelectMemo={toggleSelectMemo}
              handleTogglePin={handleTogglePin}
              openMemoDetail={openMemoDetail}
              copyMemoFullText={copyMemoFullText}
              handleToggleArchive={handleToggleArchive}
              toggleMemoActionMenu={toggleMemoActionMenu}
              openShareModal={openShareModal}
              setOpenMenuMemoId={setOpenMenuMemoId}
              setMenuPosition={setMenuPosition}
              handleDeleteMemo={handleDeleteMemo}
              handleMemoSectionDragOver={handleMemoSectionDragOver}
              handleMemoDrop={handleMemoDrop}
            />
          </div>
            </>
            )}
          </div>
        </div>

        {/* ── Memo detail modal ── */}
        <MemoDetailModal
          selectedMemo={selectedMemo}
          isMemoDetailClosing={isMemoDetailClosing}
          closeMemoDetail={closeMemoDetail}
          detailEditBackgroundColor={detailEditBackgroundColor}
          setDetailEditBackgroundColor={setDetailEditBackgroundColor}
          detailPreviewMode={detailPreviewMode}
          setDetailPreviewMode={setDetailPreviewMode}
          detailEditTitle={detailEditTitle}
          setDetailEditTitle={setDetailEditTitle}
          collections={collections}
          detailEditCollectionId={detailEditCollectionId}
          setDetailEditCollectionId={setDetailEditCollectionId}
          detailCopied={detailCopied}
          copyDetailFullText={copyDetailFullText}
          isMemoAgentOpen={isMemoAgentOpen}
          setIsMemoAgentOpen={setIsMemoAgentOpen}
          openMemoAgent={openMemoAgent}
          detailSaveStatus={detailSaveStatus}
          detailHasUnsavedChanges={detailHasUnsavedChanges}
          detailSaveError={detailSaveError}
          detailLoading={detailLoading}
          detailError={detailError}
          detailEditAiResponse={detailEditAiResponse}
          setDetailEditAiResponse={setDetailEditAiResponse}
        />

        {/* ── Share modal ── */}
        <MemoShareModal
          isShareModalOpen={isShareModalOpen}
          closeShareModal={closeShareModal}
          shareUrl={shareUrl}
          shareStatus={shareStatus}
          copyShareLink={copyShareLink}
          openNativeShareSheet={openNativeShareSheet}
          shareLoading={shareLoading}
          supportsNativeShare={supportsNativeShare}
          shareSnsLinks={shareSnsLinks}
        />

        {/* ── Collection management panel ── */}
        <MemoCollectionModal
          isCollectionPanelOpen={isCollectionPanelOpen}
          setIsCollectionPanelOpen={setIsCollectionPanelOpen}
          collections={collections}
          newCollectionName={newCollectionName}
          setNewCollectionName={setNewCollectionName}
          newCollectionColor={newCollectionColor}
          setNewCollectionColor={setNewCollectionColor}
          collectionActionLoading={collectionActionLoading}
          handleCreateCollection={handleCreateCollection}
          editingCollectionId={editingCollectionId}
          setEditingCollectionId={setEditingCollectionId}
          editingCollectionName={editingCollectionName}
          setEditingCollectionName={setEditingCollectionName}
          editingCollectionColor={editingCollectionColor}
          setEditingCollectionColor={setEditingCollectionColor}
          handleUpdateCollection={handleUpdateCollection}
          handleDeleteCollection={handleDeleteCollection}
        />

        {/* ── Export modal ── */}
        <MemoExportModal
          isExportModalOpen={isExportModalOpen}
          setIsExportModalOpen={setIsExportModalOpen}
          exportFormat={exportFormat}
          setExportFormat={setExportFormat}
          exportScope={exportScope}
          setExportScope={setExportScope}
          exportSelectedIds={exportSelectedIds}
          exportSelectedCount={exportSelectedCount}
          allVisibleExportSelected={allVisibleExportSelected}
          clearExportSelection={clearExportSelection}
          selectAllExportMemos={selectAllExportMemos}
          toggleExportMemo={toggleExportMemo}
          canDownloadExport={canDownloadExport}
          handleExport={handleExport}
          memos={memos}
        />
      </div>
    </>
  );
}
