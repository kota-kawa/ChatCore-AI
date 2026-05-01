import { SeoHead } from "../components/SeoHead";
import { useRouter } from "next/router";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type FormEvent,
} from "react";
import useSWR from "swr";

import "../scripts/core/csrf";
import { InlineLoading } from "../components/ui/inline_loading";
import { formatDateTime } from "../lib/datetime";
import { formatLLMOutput } from "../scripts/chat/chat_ui";
import { copyTextToClipboard, renderSanitizedHTML } from "../scripts/chat/message_utils";
import { setLoggedInState } from "../scripts/core/app_state";
import { fetchJsonOrThrow } from "../scripts/core/runtime_validation";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Collection = {
  id: number;
  name: string;
  color: string;
  memo_count: number;
};

type MemoSummary = {
  id: number | string;
  title?: string;
  tags?: string;
  created_at?: string | null;
  updated_at?: string | null;
  archived_at?: string | null;
  pinned_at?: string | null;
  is_archived?: boolean;
  is_pinned?: boolean;
  excerpt?: string;
  share_token?: string;
  expires_at?: string | null;
  revoked_at?: string | null;
  is_expired?: boolean;
  is_revoked?: boolean;
  is_active?: boolean;
  share_url?: string;
  collection_id?: number | null;
  collection_name?: string | null;
  collection_color?: string | null;
};

type MemoDetail = MemoSummary & {
  input_content?: string;
  ai_response?: string;
};

type MemoListPayload = { memos?: MemoSummary[]; total?: number; error?: string };
type MemoListState = { memos: MemoSummary[]; total: number };
type MemoDetailPayload = { memo?: MemoDetail; error?: string };
type SharePayload = {
  share_token?: string;
  share_url?: string;
  expires_at?: string | null;
  revoked_at?: string | null;
  is_expired?: boolean;
  is_revoked?: boolean;
  is_active?: boolean;
  is_reused?: boolean;
  error?: string;
};
type CollectionListPayload = { collections?: Collection[]; error?: string };
type FlashState = { type: "success" | "error"; text: string };
type HttpError = Error & { status?: number };
type BulkAction = "delete" | "archive" | "unarchive" | "pin" | "unpin" | "add_tags" | "set_collection" | "clear_collection";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DEFAULT_LIMIT = 50;
const MEMO_SHARE_TITLE = "Chat Core 共有メモ";
const MEMO_SHARE_TEXT = "このメモを共有しました。";
const SHARE_EXPIRES_OPTIONS = [
  { value: "7", label: "7日で期限切れ" },
  { value: "30", label: "30日で期限切れ" },
  { value: "90", label: "90日で期限切れ" },
  { value: "never", label: "無期限" },
] as const;
const EXPORT_FORMATS = [
  { value: "markdown", label: "Markdown (.md)", icon: "bi-markdown" },
  { value: "json", label: "JSON (.json)", icon: "bi-filetype-json" },
  { value: "csv", label: "CSV (.csv)", icon: "bi-filetype-csv" },
] as const;

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

function parseMemoText(raw: string | null | undefined) {
  if (!raw) return "";
  try {
    const parsed = JSON.parse(raw);
    return typeof parsed === "string" ? parsed : "";
  } catch {
    return raw;
  }
}

function splitTags(raw: string | undefined) {
  if (!raw) return [];
  return raw.split(/[,\s、，]+/).map((t) => t.trim()).filter(Boolean);
}

function buildMemoListUrl(options: {
  query: string;
  tag: string;
  dateFrom: string;
  dateTo: string;
  sort: string;
  archiveScope: string;
  collectionId: number | null;
}) {
  const params = new URLSearchParams();
  params.set("limit", String(DEFAULT_LIMIT));
  params.set("offset", "0");
  params.set("sort", options.sort);
  params.set("pinned_first", "1");

  const tq = options.query.trim();
  const tt = options.tag.trim();
  if (tq) params.set("q", tq);
  if (tt) params.set("tag", tt);
  if (options.dateFrom) params.set("date_from", options.dateFrom);
  if (options.dateTo) params.set("date_to", options.dateTo);
  if (options.archiveScope === "all") params.set("include_archived", "1");
  else if (options.archiveScope === "archived") params.set("only_archived", "1");
  if (options.collectionId !== null) params.set("collection_id", String(options.collectionId));

  return `/memo/api/recent?${params.toString()}`;
}

const loadMemoList = async (url: string): Promise<MemoListState> => {
  const res = await fetch(url, { credentials: "same-origin" });
  const data: MemoListPayload = await res.json().catch(() => ({}));
  if (res.status === 401) return { memos: [], total: 0 };
  if (!res.ok) {
    const error = new Error(data.error || `メモの取得に失敗しました (${res.status})`) as HttpError;
    (error as HttpError).status = res.status;
    throw error;
  }
  return {
    memos: Array.isArray(data.memos) ? data.memos : [],
    total: typeof data.total === "number" ? data.total : 0,
  };
};

const loadCollections = async (): Promise<Collection[]> => {
  const res = await fetch("/memo/api/collections", { credentials: "same-origin" });
  const data: CollectionListPayload = await res.json().catch(() => ({}));
  if (!res.ok) return [];
  return Array.isArray(data.collections) ? data.collections : [];
};

async function loadMemoDetail(memoId: string | number) {
  const { payload } = await fetchJsonOrThrow<MemoDetailPayload>(
    `/memo/api/${memoId}`,
    { credentials: "same-origin" },
    { defaultMessage: "メモの詳細取得に失敗しました。", hasApplicationError: (d) => !d.memo },
  );
  return payload.memo || null;
}

// ---------------------------------------------------------------------------
// MemoMarkdown component (renders LLM-formatted markdown)
// ---------------------------------------------------------------------------

function MemoMarkdown({ text, className }: { text: string; className?: string }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!containerRef.current) return;
    renderSanitizedHTML(containerRef.current, formatLLMOutput(text || ""));
  }, [text]);
  return <div ref={containerRef} className={className}></div>;
}

// ---------------------------------------------------------------------------
// CollectionBadge
// ---------------------------------------------------------------------------

function CollectionBadge({ name, color }: { name: string; color: string }) {
  return (
    <span className="memo-collection-badge" style={{ "--badge-color": color } as React.CSSProperties}>
      <i className="bi bi-folder2" aria-hidden="true"></i>
      {name}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function MemoPage() {
  const router = useRouter();

  // Form state
  const [formState, setFormState] = useState({
    input_content: "",
    ai_response: "",
    title: "",
    tags: "",
    collection_id: null as number | null,
  });
  const [previewMode, setPreviewMode] = useState(false);
  const [flashState, setFlashState] = useState<FlashState | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [aiSuggesting, setAiSuggesting] = useState(false);
  const [isLoggedIn, setIsLoggedIn] = useState(false);

  // Filter/sort state
  const [query, setQuery] = useState("");
  const [tagFilter, setTagFilter] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [sortMode, setSortMode] = useState("recent");
  const [archiveScope, setArchiveScope] = useState("active");
  const [activeCollectionId, setActiveCollectionId] = useState<number | null>(null);

  // Mobile tab
  const [activeMobileTab, setActiveMobileTab] = useState<"list" | "compose">("list");

  // Detail modal
  const [selectedMemo, setSelectedMemo] = useState<MemoDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");

  // Quick edit
  const [editingMemoId, setEditingMemoId] = useState<string>("");
  const [quickEditTitle, setQuickEditTitle] = useState("");
  const [quickEditTags, setQuickEditTags] = useState("");
  const [quickEditCollectionId, setQuickEditCollectionId] = useState<number | null>(null);
  const [actionLoadingId, setActionLoadingId] = useState<string>("");

  // Share modal
  const [isShareModalOpen, setIsShareModalOpen] = useState(false);
  const [shareMemoId, setShareMemoId] = useState<string>("");
  const [shareMemoTitle, setShareMemoTitle] = useState("");
  const [shareState, setShareState] = useState<SharePayload | null>(null);
  const [shareStatus, setShareStatus] = useState<FlashState | null>(null);
  const [shareLoading, setShareLoading] = useState(false);
  const [shareExpiry, setShareExpiry] = useState<(typeof SHARE_EXPIRES_OPTIONS)[number]["value"]>("30");
  const [supportsNativeShare, setSupportsNativeShare] = useState(false);

  // Bulk selection
  const [isBulkMode, setIsBulkMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkTagInput, setBulkTagInput] = useState("");
  const [bulkCollectionId, setBulkCollectionId] = useState<number | null>(null);
  const [bulkLoading, setBulkLoading] = useState(false);

  // Collections sidebar
  const [isCollectionPanelOpen, setIsCollectionPanelOpen] = useState(false);
  const [newCollectionName, setNewCollectionName] = useState("");
  const [newCollectionColor, setNewCollectionColor] = useState("#6b7280");
  const [collectionActionLoading, setCollectionActionLoading] = useState(false);
  const [editingCollectionId, setEditingCollectionId] = useState<number | null>(null);
  const [editingCollectionName, setEditingCollectionName] = useState("");
  const [editingCollectionColor, setEditingCollectionColor] = useState("#6b7280");

  // Export modal
  const [isExportModalOpen, setIsExportModalOpen] = useState(false);
  const [exportFormat, setExportFormat] = useState<"markdown" | "json" | "csv">("markdown");
  const [exportScope, setExportScope] = useState<"all" | "selected">("all");

  // -----------------------------------------------------------------------
  // Data fetching
  // -----------------------------------------------------------------------

  const listUrl = useMemo(
    () => buildMemoListUrl({ query, tag: tagFilter, dateFrom, dateTo, sort: sortMode, archiveScope, collectionId: activeCollectionId }),
    [archiveScope, dateFrom, dateTo, query, sortMode, tagFilter, activeCollectionId],
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

  const topTags = useMemo(() => {
    const counts = new Map<string, number>();
    for (const memo of memos) {
      for (const tag of splitTags(memo.tags)) {
        counts.set(tag, (counts.get(tag) || 0) + 1);
      }
    }
    return Array.from(counts.entries())
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      .slice(0, 8);
  }, [memos]);

  const shareUrl = (shareState?.share_url || "").trim();
  const shareSnsLinks = useMemo(() => {
    if (!shareUrl) return { x: "#", line: "#", facebook: "#" };
    const eu = encodeURIComponent(shareUrl);
    const et = encodeURIComponent(MEMO_SHARE_TEXT);
    return {
      x: `https://twitter.com/intent/tweet?url=${eu}&text=${et}`,
      line: `https://social-plugins.line.me/lineit/share?url=${eu}`,
      facebook: `https://www.facebook.com/sharer/sharer.php?u=${eu}`,
    };
  }, [shareUrl]);

  // -----------------------------------------------------------------------
  // Effects
  // -----------------------------------------------------------------------

  useEffect(() => {
    document.body.classList.add("memo-page");
    const importCustomElements = async () => {
      await Promise.all([import("../scripts/components/popup_menu"), import("../scripts/components/user_icon")]);
    };
    void importCustomElements();
    setSupportsNativeShare(typeof navigator !== "undefined" && typeof navigator.share === "function");
    return () => {
      document.body.classList.remove("memo-page");
      document.body.classList.remove("modal-open");
    };
  }, []);

  useEffect(() => {
    const open = Boolean(selectedMemo) || isShareModalOpen || isCollectionPanelOpen || isExportModalOpen;
    document.body.classList.toggle("modal-open", open);
    return () => { document.body.classList.remove("modal-open"); };
  }, [isShareModalOpen, selectedMemo, isCollectionPanelOpen, isExportModalOpen]);

  useEffect(() => {
    const syncAuthState = async () => {
      try {
        const res = await fetch("/api/current_user", { credentials: "same-origin" });
        const data = res.ok ? await res.json() : { logged_in: false };
        const loggedIn = Boolean(data.logged_in);
        setIsLoggedIn(loggedIn);
        setLoggedInState(loggedIn);
      } catch {
        setIsLoggedIn(false);
        setLoggedInState(false);
      }
    };
    void syncAuthState();
  }, []);

  useEffect(() => {
    if (!router.isReady) return;
    if (router.query.saved === "1") setFlashState({ type: "success", text: "メモを保存しました。" });
  }, [router.isReady, router.query.saved]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (isExportModalOpen) { setIsExportModalOpen(false); return; }
      if (isCollectionPanelOpen) { setIsCollectionPanelOpen(false); return; }
      if (isShareModalOpen) { setIsShareModalOpen(false); return; }
      if (selectedMemo) setSelectedMemo(null);
    };
    document.addEventListener("keydown", onKeyDown);
    return () => { document.removeEventListener("keydown", onKeyDown); };
  }, [isShareModalOpen, selectedMemo, isCollectionPanelOpen, isExportModalOpen]);

  // Exit bulk mode when memos change drastically
  useEffect(() => {
    if (!isBulkMode) return;
    setSelectedIds((prev) => {
      const memoIdSet = new Set(memos.map((m) => String(m.id)));
      const next = new Set([...prev].filter((id) => memoIdSet.has(id)));
      return next.size === prev.size ? prev : next;
    });
  }, [memos, isBulkMode]);

  // -----------------------------------------------------------------------
  // Helpers
  // -----------------------------------------------------------------------

  const showFlash = useCallback((type: "success" | "error", text: string) => {
    setFlashState({ type, text });
    setTimeout(() => setFlashState(null), 4000);
  }, []);

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

  const handleSubmitMemo = useCallback(async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setFlashState(null);
    if (!formState.ai_response.trim()) { showFlash("error", "AIの回答を入力してください。"); return; }
    setSubmitting(true);
    try {
      await fetchJsonOrThrow(
        "/memo/api",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify(formState),
        },
        { defaultMessage: "メモの保存に失敗しました。" },
      );
      setFormState({ input_content: "", ai_response: "", title: "", tags: "", collection_id: null });
      setPreviewMode(false);
      showFlash("success", "メモを保存しました。");
      setActiveMobileTab("list");
      void router.replace("/memo?saved=1", undefined, { shallow: true });
      void mutate();
    } catch (error) {
      showFlash("error", error instanceof Error ? error.message : "メモの保存に失敗しました。");
    } finally {
      setSubmitting(false);
    }
  }, [formState, mutate, router, showFlash]);

  const handleAiSuggest = useCallback(async () => {
    if (!formState.ai_response.trim()) { showFlash("error", "AIの回答を先に入力してください。"); return; }
    setAiSuggesting(true);
    try {
      const { payload } = await fetchJsonOrThrow<{ title?: string; tags?: string }>(
        "/memo/api/suggest",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ input_content: formState.input_content, ai_response: formState.ai_response }),
        },
        { defaultMessage: "AI提案の取得に失敗しました。" },
      );
      setFormState((prev) => ({
        ...prev,
        title: payload.title || prev.title,
        tags: payload.tags || prev.tags,
      }));
      showFlash("success", "AIがタイトルとタグを提案しました。");
    } catch (error) {
      showFlash("error", error instanceof Error ? error.message : "AI提案に失敗しました。");
    } finally {
      setAiSuggesting(false);
    }
  }, [formState.ai_response, formState.input_content, showFlash]);

  // -----------------------------------------------------------------------
  // Memo detail
  // -----------------------------------------------------------------------

  const openMemoDetail = useCallback(async (memoId: string | number) => {
    setDetailError("");
    setDetailLoading(true);
    try {
      const memo = await loadMemoDetail(memoId);
      if (!memo) { setDetailError("メモの詳細を取得できませんでした。"); return; }
      setSelectedMemo(memo);
    } catch (error) {
      setDetailError(error instanceof Error ? error.message : "メモの詳細取得に失敗しました。");
    } finally {
      setDetailLoading(false);
    }
  }, []);

  // -----------------------------------------------------------------------
  // Pin / Archive / Delete
  // -----------------------------------------------------------------------

  const handleTogglePin = useCallback(async (memo: MemoSummary) => {
    await withActionLoading(memo.id, async () => {
      try {
        await fetchJsonOrThrow(
          `/memo/api/${memo.id}/pin`,
          { method: "POST", headers: { "Content-Type": "application/json" }, credentials: "same-origin", body: JSON.stringify({ enabled: !memo.is_pinned }) },
          { defaultMessage: "ピン留め更新に失敗しました。" },
        );
        showFlash("success", memo.is_pinned ? "ピン留めを解除しました。" : "ピン留めしました。");
        await mutate();
        await refreshSelectedMemoIfNeeded();
      } catch (error) { showFlash("error", error instanceof Error ? error.message : "ピン留め更新に失敗しました。"); }
    });
  }, [mutate, refreshSelectedMemoIfNeeded, showFlash, withActionLoading]);

  const handleToggleArchive = useCallback(async (memo: MemoSummary) => {
    await withActionLoading(memo.id, async () => {
      try {
        await fetchJsonOrThrow(
          `/memo/api/${memo.id}/archive`,
          { method: "POST", headers: { "Content-Type": "application/json" }, credentials: "same-origin", body: JSON.stringify({ enabled: !memo.is_archived }) },
          { defaultMessage: "アーカイブ更新に失敗しました。" },
        );
        showFlash("success", memo.is_archived ? "アーカイブを解除しました。" : "アーカイブしました。");
        await mutate();
        await refreshSelectedMemoIfNeeded();
      } catch (error) { showFlash("error", error instanceof Error ? error.message : "アーカイブ更新に失敗しました。"); }
    });
  }, [mutate, refreshSelectedMemoIfNeeded, showFlash, withActionLoading]);

  const handleDeleteMemo = useCallback(async (memo: MemoSummary) => {
    const confirmed = window.confirm(`「${memo.title || "保存したメモ"}」を削除しますか？`);
    if (!confirmed) return;
    await withActionLoading(memo.id, async () => {
      try {
        await fetchJsonOrThrow(
          `/memo/api/${memo.id}`,
          { method: "DELETE", credentials: "same-origin" },
          { defaultMessage: "メモの削除に失敗しました。" },
        );
        showFlash("success", "メモを削除しました。");
        if (selectedMemo?.id && String(selectedMemo.id) === String(memo.id)) setSelectedMemo(null);
        await mutate();
      } catch (error) { showFlash("error", error instanceof Error ? error.message : "メモの削除に失敗しました。"); }
    });
  }, [mutate, selectedMemo?.id, showFlash, withActionLoading]);

  // -----------------------------------------------------------------------
  // Quick edit
  // -----------------------------------------------------------------------

  const startQuickEdit = useCallback((memo: MemoSummary) => {
    setEditingMemoId(String(memo.id));
    setQuickEditTitle(memo.title || "");
    setQuickEditTags(memo.tags || "");
    setQuickEditCollectionId(memo.collection_id ?? null);
  }, []);

  const cancelQuickEdit = useCallback(() => {
    setEditingMemoId("");
    setQuickEditTitle("");
    setQuickEditTags("");
    setQuickEditCollectionId(null);
  }, []);

  const saveQuickEdit = useCallback(async (memoId: string | number) => {
    await withActionLoading(memoId, async () => {
      try {
        const body: Record<string, unknown> = { title: quickEditTitle, tags: quickEditTags };
        if (quickEditCollectionId !== null) {
          body.collection_id = quickEditCollectionId;
        } else {
          body.clear_collection = true;
        }
        await fetchJsonOrThrow(
          `/memo/api/${memoId}`,
          { method: "PATCH", headers: { "Content-Type": "application/json" }, credentials: "same-origin", body: JSON.stringify(body) },
          { defaultMessage: "メモ更新に失敗しました。" },
        );
        cancelQuickEdit();
        showFlash("success", "メモを更新しました。");
        await mutate();
        await refreshSelectedMemoIfNeeded();
      } catch (error) { showFlash("error", error instanceof Error ? error.message : "メモ更新に失敗しました。"); }
    });
  }, [cancelQuickEdit, mutate, quickEditCollectionId, quickEditTags, quickEditTitle, refreshSelectedMemoIfNeeded, showFlash, withActionLoading]);

  const copyMemoExcerpt = useCallback(async (memo: MemoSummary) => {
    const content = `${memo.title || "保存したメモ"}\n\n${parseMemoText(memo.excerpt)}`;
    try {
      await copyTextToClipboard(content.trim());
      showFlash("success", "メモの要約をコピーしました。");
    } catch (error) { showFlash("error", error instanceof Error ? error.message : "コピーに失敗しました。"); }
  }, [showFlash]);

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

  const executeBulkAction = useCallback(async (action: BulkAction, extra?: { tags?: string; collectionId?: number | null }) => {
    if (selectedIds.size === 0) return;
    setBulkLoading(true);
    try {
      const body: Record<string, unknown> = {
        action,
        memo_ids: Array.from(selectedIds).map(Number),
      };
      if (extra?.tags !== undefined) body.tags = extra.tags;
      if (extra?.collectionId !== undefined) body.collection_id = extra.collectionId;

      await fetchJsonOrThrow(
        "/memo/api/bulk",
        { method: "POST", headers: { "Content-Type": "application/json" }, credentials: "same-origin", body: JSON.stringify(body) },
        { defaultMessage: "一括操作に失敗しました。" },
      );
      const labels: Record<BulkAction, string> = {
        delete: "削除", archive: "アーカイブ", unarchive: "アーカイブ解除",
        pin: "ピン留め", unpin: "ピン留め解除", add_tags: "タグ追加",
        set_collection: "コレクション設定", clear_collection: "コレクション解除",
      };
      showFlash("success", `${selectedIds.size}件を${labels[action]}しました。`);
      if (action === "delete") setSelectedIds(new Set());
      await mutate();
      setBulkTagInput("");
      setBulkCollectionId(null);
    } catch (error) {
      showFlash("error", error instanceof Error ? error.message : "一括操作に失敗しました。");
    } finally {
      setBulkLoading(false);
    }
  }, [mutate, selectedIds, showFlash]);

  const exitBulkMode = useCallback(() => {
    setIsBulkMode(false);
    setSelectedIds(new Set());
  }, []);

  // -----------------------------------------------------------------------
  // Share modal
  // -----------------------------------------------------------------------

  const loadShareState = useCallback(async (memoId: string | number) => {
    const { payload } = await fetchJsonOrThrow<SharePayload>(
      `/memo/api/${memoId}/share`,
      { credentials: "same-origin" },
      { defaultMessage: "共有情報の取得に失敗しました。" },
    );
    setShareState(payload);
    if (payload.expires_at) {
      const diff = Math.round((new Date(payload.expires_at).getTime() - Date.now()) / 86400000);
      if (diff <= 8 && diff > 0) setShareExpiry("7");
      else if (diff <= 32 && diff > 0) setShareExpiry("30");
      else if (diff <= 95 && diff > 0) setShareExpiry("90");
      else setShareExpiry("30");
    } else setShareExpiry("never");
  }, []);

  const openShareModal = useCallback(async (memo: MemoSummary) => {
    const memoId = String(memo.id || "");
    if (!memoId) { showFlash("error", "共有対象のメモが見つかりません。"); return; }
    setIsShareModalOpen(true);
    setShareMemoId(memoId);
    setShareMemoTitle(memo.title || "保存したメモ");
    setShareState(null);
    setShareStatus({ type: "success", text: "共有情報を読み込んでいます..." });
    setShareLoading(true);
    try {
      await loadShareState(memoId);
      setShareStatus({ type: "success", text: "共有設定を確認できます。" });
    } catch (error) {
      setShareStatus({ type: "error", text: error instanceof Error ? error.message : "共有情報の取得に失敗しました。" });
    } finally {
      setShareLoading(false);
    }
  }, [loadShareState, showFlash]);

  const closeShareModal = useCallback(() => {
    setIsShareModalOpen(false);
    setShareMemoId("");
    setShareMemoTitle("");
    setShareStatus(null);
    setShareState(null);
  }, []);

  const createShareLink = useCallback(async (forceRefresh: boolean) => {
    if (!shareMemoId) return;
    setShareLoading(true);
    setShareStatus({ type: "success", text: forceRefresh ? "共有リンクを再生成しています..." : "共有リンクを作成しています..." });
    const expiresInDays = shareExpiry === "never" ? null : Number(shareExpiry);
    try {
      const { payload } = await fetchJsonOrThrow<SharePayload>(
        `/memo/api/${shareMemoId}/share`,
        { method: "POST", headers: { "Content-Type": "application/json" }, credentials: "same-origin", body: JSON.stringify({ force_refresh: forceRefresh, expires_in_days: expiresInDays }) },
        { defaultMessage: "共有リンクの作成に失敗しました。" },
      );
      setShareState(payload);
      setShareStatus({ type: "success", text: forceRefresh ? "共有リンクを再生成しました。" : "共有リンクを作成しました。" });
      await mutate();
    } catch (error) {
      setShareStatus({ type: "error", text: error instanceof Error ? error.message : "共有リンクの作成に失敗しました。" });
    } finally {
      setShareLoading(false);
    }
  }, [mutate, shareExpiry, shareMemoId]);

  const revokeShareLink = useCallback(async () => {
    if (!shareMemoId) return;
    setShareLoading(true);
    setShareStatus({ type: "success", text: "共有リンクを無効化しています..." });
    try {
      const { payload } = await fetchJsonOrThrow<SharePayload>(
        `/memo/api/${shareMemoId}/share/revoke`,
        { method: "POST", credentials: "same-origin" },
        { defaultMessage: "共有リンクの無効化に失敗しました。" },
      );
      setShareState(payload);
      setShareStatus({ type: "success", text: "共有リンクを無効化しました。" });
      await mutate();
    } catch (error) {
      setShareStatus({ type: "error", text: error instanceof Error ? error.message : "共有リンクの無効化に失敗しました。" });
    } finally {
      setShareLoading(false);
    }
  }, [mutate, shareMemoId]);

  const copyShareLink = useCallback(async () => {
    if (!shareUrl) { setShareStatus({ type: "error", text: "先に共有リンクを作成してください。" }); return; }
    try {
      await copyTextToClipboard(shareUrl);
      setShareStatus({ type: "success", text: "共有リンクをコピーしました。" });
    } catch (error) {
      setShareStatus({ type: "error", text: error instanceof Error ? error.message : "リンクのコピーに失敗しました。" });
    }
  }, [shareUrl]);

  const openNativeShareSheet = useCallback(async () => {
    if (!shareUrl) { setShareStatus({ type: "error", text: "先に共有リンクを作成してください。" }); return; }
    if (!supportsNativeShare || typeof navigator.share !== "function") { setShareStatus({ type: "error", text: "このブラウザは端末共有に対応していません。" }); return; }
    try {
      await navigator.share({ title: MEMO_SHARE_TITLE, text: MEMO_SHARE_TEXT, url: shareUrl });
    } catch (error) {
      if (error instanceof Error && error.name === "AbortError") return;
      setShareStatus({ type: "error", text: error instanceof Error ? error.message : "端末共有に失敗しました。" });
    }
  }, [shareUrl, supportsNativeShare]);

  // -----------------------------------------------------------------------
  // Collections management
  // -----------------------------------------------------------------------

  const handleCreateCollection = useCallback(async () => {
    const name = newCollectionName.trim();
    if (!name) { showFlash("error", "コレクション名を入力してください。"); return; }
    setCollectionActionLoading(true);
    try {
      await fetchJsonOrThrow(
        "/memo/api/collections",
        { method: "POST", headers: { "Content-Type": "application/json" }, credentials: "same-origin", body: JSON.stringify({ name, color: newCollectionColor }) },
        { defaultMessage: "コレクションの作成に失敗しました。" },
      );
      setNewCollectionName("");
      setNewCollectionColor("#6b7280");
      showFlash("success", "コレクションを作成しました。");
      await mutateCollections();
    } catch (error) { showFlash("error", error instanceof Error ? error.message : "コレクションの作成に失敗しました。"); }
    finally { setCollectionActionLoading(false); }
  }, [newCollectionColor, newCollectionName, mutateCollections, showFlash]);

  const handleUpdateCollection = useCallback(async (collectionId: number) => {
    setCollectionActionLoading(true);
    try {
      await fetchJsonOrThrow(
        `/memo/api/collections/${collectionId}`,
        { method: "PATCH", headers: { "Content-Type": "application/json" }, credentials: "same-origin", body: JSON.stringify({ name: editingCollectionName, color: editingCollectionColor }) },
        { defaultMessage: "コレクションの更新に失敗しました。" },
      );
      setEditingCollectionId(null);
      showFlash("success", "コレクションを更新しました。");
      await mutateCollections();
      await mutate();
    } catch (error) { showFlash("error", error instanceof Error ? error.message : "コレクションの更新に失敗しました。"); }
    finally { setCollectionActionLoading(false); }
  }, [editingCollectionColor, editingCollectionName, mutate, mutateCollections, showFlash]);

  const handleDeleteCollection = useCallback(async (collectionId: number, name: string) => {
    const confirmed = window.confirm(`「${name}」を削除しますか？\nコレクション内のメモはコレクションから外れます。`);
    if (!confirmed) return;
    setCollectionActionLoading(true);
    try {
      await fetchJsonOrThrow(
        `/memo/api/collections/${collectionId}`,
        { method: "DELETE", credentials: "same-origin" },
        { defaultMessage: "コレクションの削除に失敗しました。" },
      );
      if (activeCollectionId === collectionId) setActiveCollectionId(null);
      showFlash("success", "コレクションを削除しました。");
      await mutateCollections();
      await mutate();
    } catch (error) { showFlash("error", error instanceof Error ? error.message : "コレクションの削除に失敗しました。"); }
    finally { setCollectionActionLoading(false); }
  }, [activeCollectionId, mutate, mutateCollections, showFlash]);

  // -----------------------------------------------------------------------
  // Export
  // -----------------------------------------------------------------------

  const handleExport = useCallback(() => {
    const ids = exportScope === "selected" && selectedIds.size > 0
      ? Array.from(selectedIds).join(",")
      : "";
    const params = new URLSearchParams({ format: exportFormat });
    if (ids) params.set("ids", ids);
    const url = `/memo/api/export?${params.toString()}`;
    const a = document.createElement("a");
    a.href = url;
    a.download = `memos.${exportFormat === "json" ? "json" : exportFormat === "csv" ? "csv" : "md"}`;
    a.click();
    setIsExportModalOpen(false);
    showFlash("success", "エクスポートを開始しました。");
  }, [exportFormat, exportScope, selectedIds, showFlash]);

  // -----------------------------------------------------------------------
  // Render
  // -----------------------------------------------------------------------

  const hasSelection = selectedIds.size > 0;

  return (
    <>
      <SeoHead
        title="メモを保存 | Chat Core"
        description="Chat CoreでAIとのやり取りや作業メモを保存し、検索・整理・共有できるページです。"
        canonicalPath="/memo"
        noindex
      >
        <link rel="stylesheet" href="/memo/static/css/memo_form.css" />
      </SeoHead>

      <div className="memo-page-shell">
        <action-menu></action-menu>

        <div
          id="auth-buttons"
          style={{ display: isLoggedIn ? "none" : "", position: "fixed", top: "10px", right: "10px", zIndex: "var(--z-floating-controls)" }}
        >
          <button type="button" id="login-btn" className="auth-btn" onClick={() => { window.location.href = "/login"; }}>
            <i className="bi bi-person-circle"></i>
            <span>ログイン / 登録</span>
          </button>
        </div>

        <user-icon id="userIcon" style={{ display: isLoggedIn ? "" : "none" }}></user-icon>

        <div className="memo-container">
          {/* ── Toolbar ── */}
          <header className="memo-toolbar memo-card">
            <div className="memo-toolbar__top-row">
              <div className="memo-toolbar__title">
                <h1>メモワークスペース</h1>
                <p>検索・整理・共有を1ページで完結。保存した会話をすぐ再利用できます。</p>
              </div>
              <div className="memo-toolbar__actions">
                <button
                  type="button"
                  className={`memo-toolbar__icon-btn${isBulkMode ? " is-active" : ""}`}
                  onClick={() => { if (isBulkMode) exitBulkMode(); else setIsBulkMode(true); }}
                  title={isBulkMode ? "一括選択を終了" : "一括操作モード"}
                >
                  <i className={`bi ${isBulkMode ? "bi-check2-square" : "bi-ui-checks"}`}></i>
                  <span className="memo-toolbar__btn-label">{isBulkMode ? "選択終了" : "一括操作"}</span>
                </button>
                <button
                  type="button"
                  className="memo-toolbar__icon-btn"
                  onClick={() => setIsCollectionPanelOpen(true)}
                  title="コレクション管理"
                >
                  <i className="bi bi-folder2-open"></i>
                  <span className="memo-toolbar__btn-label">コレクション</span>
                </button>
                <button
                  type="button"
                  className="memo-toolbar__icon-btn"
                  onClick={() => setIsExportModalOpen(true)}
                  title="エクスポート"
                >
                  <i className="bi bi-download"></i>
                  <span className="memo-toolbar__btn-label">エクスポート</span>
                </button>
              </div>
            </div>

            <div className="memo-toolbar__search">
              <label htmlFor="memo-search" className="sr-only">メモを検索</label>
              <i className="bi bi-search" aria-hidden="true"></i>
              <input
                id="memo-search"
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="タイトル・タグ・本文から検索"
              />
              {sortMode === "semantic" && <span className="memo-search__badge">AI検索</span>}
            </div>

            <div className="memo-toolbar__filters">
              <input
                type="text"
                className="memo-toolbar__tag-filter"
                value={tagFilter}
                onChange={(e) => setTagFilter(e.target.value)}
                placeholder="タグで絞り込み"
              />
              <label className="memo-toolbar__date-filter">
                <span>開始日</span>
                <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
              </label>
              <label className="memo-toolbar__date-filter">
                <span>終了日</span>
                <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
              </label>
              <select value={sortMode} onChange={(e) => setSortMode(e.target.value)}>
                <option value="recent">新しい順</option>
                <option value="updated">更新順</option>
                <option value="oldest">古い順</option>
                <option value="title">タイトル順</option>
                <option value="semantic">AI類似検索</option>
              </select>
              <select value={archiveScope} onChange={(e) => setArchiveScope(e.target.value)}>
                <option value="active">通常メモ</option>
                <option value="all">すべて</option>
                <option value="archived">アーカイブのみ</option>
              </select>
              <button
                type="button"
                className="memo-toolbar__clear"
                onClick={() => { setQuery(""); setTagFilter(""); setDateFrom(""); setDateTo(""); setArchiveScope("active"); setSortMode("recent"); setActiveCollectionId(null); }}
              >
                クリア
              </button>
            </div>

            {/* Collection filter chips */}
            {collections.length > 0 && (
              <div className="memo-toolbar__collections" aria-label="コレクション">
                <button
                  type="button"
                  className={`memo-collection-chip${activeCollectionId === null ? " is-active" : ""}`}
                  onClick={() => setActiveCollectionId(null)}
                >
                  <i className="bi bi-grid-3x3-gap" aria-hidden="true"></i>
                  すべて
                </button>
                {collections.map((col) => (
                  <button
                    type="button"
                    key={col.id}
                    className={`memo-collection-chip${activeCollectionId === col.id ? " is-active" : ""}`}
                    style={{ "--badge-color": col.color } as React.CSSProperties}
                    onClick={() => setActiveCollectionId((prev) => (prev === col.id ? null : col.id))}
                  >
                    <i className="bi bi-folder2" aria-hidden="true"></i>
                    {col.name}
                    <span className="memo-collection-chip__count">{col.memo_count}</span>
                  </button>
                ))}
              </div>
            )}

            {/* Tag chips */}
            {topTags.length > 0 && (
              <div className="memo-toolbar__chips" aria-label="人気タグ">
                {topTags.map(([tag, count]) => (
                  <button
                    type="button"
                    key={tag}
                    className={`memo-chip${tagFilter === tag ? " is-active" : ""}`}
                    onClick={() => setTagFilter((prev) => (prev === tag ? "" : tag))}
                  >
                    #{tag}
                    <span>{count}</span>
                  </button>
                ))}
              </div>
            )}
          </header>

          {flashState && (
            <div className={`memo-flash memo-flash--${flashState.type}`} role="alert">
              {flashState.text}
            </div>
          )}

          {/* Bulk action bar */}
          {isBulkMode && (
            <div className="memo-bulk-bar memo-card" role="toolbar" aria-label="一括操作バー">
              <div className="memo-bulk-bar__info">
                <input
                  type="checkbox"
                  id="bulk-select-all"
                  className="memo-bulk-checkbox"
                  checked={hasSelection && selectedIds.size === memos.length}
                  onChange={(e) => { if (e.target.checked) selectAll(); else deselectAll(); }}
                />
                <label htmlFor="bulk-select-all" className="memo-bulk-bar__count">
                  {hasSelection ? `${selectedIds.size}件選択中` : "すべて選択"}
                </label>
              </div>
              <div className="memo-bulk-bar__actions">
                <button type="button" className="memo-bulk-btn" onClick={() => void executeBulkAction("pin")} disabled={!hasSelection || bulkLoading} title="ピン留め">
                  <i className="bi bi-pin-angle"></i>ピン留め
                </button>
                <button type="button" className="memo-bulk-btn" onClick={() => void executeBulkAction("unpin")} disabled={!hasSelection || bulkLoading} title="ピン留め解除">
                  <i className="bi bi-pin-angle-fill"></i>解除
                </button>
                <button type="button" className="memo-bulk-btn" onClick={() => void executeBulkAction("archive")} disabled={!hasSelection || bulkLoading} title="アーカイブ">
                  <i className="bi bi-archive"></i>アーカイブ
                </button>
                <button type="button" className="memo-bulk-btn" onClick={() => void executeBulkAction("unarchive")} disabled={!hasSelection || bulkLoading} title="アーカイブ解除">
                  <i className="bi bi-archive-fill"></i>解除
                </button>
                <div className="memo-bulk-bar__tag-group">
                  <input
                    type="text"
                    className="memo-bulk-tag-input"
                    value={bulkTagInput}
                    onChange={(e) => setBulkTagInput(e.target.value)}
                    placeholder="タグを追加"
                  />
                  <button type="button" className="memo-bulk-btn" onClick={() => void executeBulkAction("add_tags", { tags: bulkTagInput })} disabled={!hasSelection || bulkLoading || !bulkTagInput.trim()} title="タグを追加">
                    <i className="bi bi-tag"></i>タグ追加
                  </button>
                </div>
                {collections.length > 0 && (
                  <div className="memo-bulk-bar__tag-group">
                    <select
                      className="memo-bulk-collection-select"
                      value={bulkCollectionId ?? ""}
                      onChange={(e) => setBulkCollectionId(e.target.value === "" ? null : Number(e.target.value))}
                    >
                      <option value="">コレクション選択</option>
                      {collections.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                    </select>
                    <button type="button" className="memo-bulk-btn" onClick={() => void executeBulkAction("set_collection", { collectionId: bulkCollectionId })} disabled={!hasSelection || bulkLoading || bulkCollectionId === null} title="コレクション設定">
                      <i className="bi bi-folder2"></i>設定
                    </button>
                    <button type="button" className="memo-bulk-btn" onClick={() => void executeBulkAction("clear_collection")} disabled={!hasSelection || bulkLoading} title="コレクション解除">
                      解除
                    </button>
                  </div>
                )}
                <button type="button" className="memo-bulk-btn memo-bulk-btn--danger" onClick={() => void executeBulkAction("delete")} disabled={!hasSelection || bulkLoading} title="削除">
                  <i className="bi bi-trash3"></i>削除
                </button>
              </div>
            </div>
          )}

          {/* Mobile tabs */}
          <div className="memo-mobile-tabs" role="tablist" aria-label="メモ画面タブ">
            <button type="button" role="tab" aria-selected={activeMobileTab === "list"} className={activeMobileTab === "list" ? "is-active" : ""} onClick={() => setActiveMobileTab("list")}>メモ一覧</button>
            <button type="button" role="tab" aria-selected={activeMobileTab === "compose"} className={activeMobileTab === "compose" ? "is-active" : ""} onClick={() => setActiveMobileTab("compose")}>新規作成</button>
          </div>

          <div className={`memo-grid${activeMobileTab === "compose" ? " show-compose" : " show-list"}`}>
            {/* ── Memo list ── */}
            <section className="memo-card memo-history-panel">
              <div className="memo-panel__header">
                <h2>メモ一覧{activeCollectionId !== null && collections.find(c => c.id === activeCollectionId) && <span className="memo-panel__collection-label"> — {collections.find(c => c.id === activeCollectionId)?.name}</span>}</h2>
                <p>{totalMemoCount}件</p>
              </div>

              {memoLoadError && <div className="memo-history__empty">{memoLoadError.message}</div>}
              {!memoLoadError && memoListLoading && memos.length === 0 && (
                <div className="memo-history__empty"><InlineLoading label="メモを読み込んでいます..." className="mx-auto" /></div>
              )}
              {!memoLoadError && !memoListLoading && memos.length === 0 && (
                <div className="memo-history__empty">条件に一致するメモがありません。</div>
              )}

              {memos.length > 0 && (
                <ul className="memo-history__list">
                  {memos.map((memo) => {
                    const memoId = String(memo.id);
                    const isEditing = editingMemoId === memoId;
                    const isBusy = actionLoadingId === memoId;
                    const isSelected = selectedIds.has(memoId);
                    const tags = splitTags(memo.tags);

                    return (
                      <li key={memoId}>
                        <article className={`memo-item${memo.is_archived ? " is-archived" : ""}${memo.is_pinned ? " is-pinned" : ""}${isSelected ? " is-selected" : ""}`}>
                          {isBulkMode && (
                            <div className="memo-item__checkbox-wrap">
                              <input
                                type="checkbox"
                                className="memo-bulk-checkbox"
                                checked={isSelected}
                                onChange={() => toggleSelectMemo(memoId)}
                                aria-label={`${memo.title || "保存したメモ"}を選択`}
                              />
                            </div>
                          )}

                          <div className="memo-item__header">
                            <button
                              type="button"
                              className="memo-item__open"
                              onClick={() => { if (isBulkMode) { toggleSelectMemo(memoId); return; } void openMemoDetail(memoId); }}
                            >
                              <div className="memo-item__heading">
                                <h3 className="memo-item__title">{memo.title || "保存したメモ"}</h3>
                                <time className="memo-item__date">
                                  {formatDateTime(memo.updated_at || memo.created_at) || memo.updated_at || memo.created_at || ""}
                                </time>
                              </div>
                            </button>
                            <div className="memo-item__status-icons" aria-label="メモ状態">
                              {memo.is_pinned && <i className="bi bi-pin-angle-fill" title="ピン留め中"></i>}
                              {memo.is_archived && <i className="bi bi-archive-fill" title="アーカイブ中"></i>}
                              {memo.is_active && <i className="bi bi-link-45deg" title="共有中"></i>}
                            </div>
                          </div>

                          {isEditing ? (
                            <div className="memo-item__inline-edit">
                              <input
                                type="text"
                                value={quickEditTitle}
                                onChange={(e) => setQuickEditTitle(e.target.value)}
                                placeholder="タイトル"
                                maxLength={255}
                              />
                              <input
                                type="text"
                                value={quickEditTags}
                                onChange={(e) => setQuickEditTags(e.target.value)}
                                placeholder="タグ（スペース区切り）"
                                maxLength={255}
                              />
                              {collections.length > 0 && (
                                <select
                                  value={quickEditCollectionId ?? ""}
                                  onChange={(e) => setQuickEditCollectionId(e.target.value === "" ? null : Number(e.target.value))}
                                  className="memo-item__collection-select"
                                >
                                  <option value="">コレクションなし</option>
                                  {collections.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                                </select>
                              )}
                              <div className="memo-item__inline-actions">
                                <button type="button" onClick={() => { void saveQuickEdit(memoId); }} disabled={isBusy}>保存</button>
                                <button type="button" onClick={cancelQuickEdit} disabled={isBusy}>キャンセル</button>
                              </div>
                            </div>
                          ) : (
                            <>
                              <button
                                type="button"
                                className="memo-item__open memo-item__open--content"
                                onClick={() => { if (isBulkMode) { toggleSelectMemo(memoId); return; } void openMemoDetail(memoId); }}
                              >
                                <div className="memo-item__meta-row">
                                  {memo.collection_name && (
                                    <CollectionBadge name={memo.collection_name} color={memo.collection_color || "#6b7280"} />
                                  )}
                                  <div className="memo-tag-list">
                                    {tags.length
                                      ? tags.map((tag) => <span key={tag} className="memo-tag">{tag}</span>)
                                      : <span className="memo-tag memo-tag--muted">タグなし</span>}
                                  </div>
                                </div>
                                {memo.excerpt && <MemoMarkdown text={parseMemoText(memo.excerpt)} className="memo-item__excerpt" />}
                              </button>

                              {!isBulkMode && (
                                <div className="memo-item__actions">
                                  {tags.map((tag) => (
                                    <button
                                      type="button"
                                      key={tag}
                                      className="memo-item__tag-action"
                                      onClick={() => setTagFilter(tag)}
                                      disabled={isBusy}
                                      title={`${tag} で絞り込み`}
                                    >
                                      #{tag}
                                    </button>
                                  ))}
                                  <button type="button" className="memo-item__action" onClick={() => { void copyMemoExcerpt(memo); }} disabled={isBusy} title="要約をコピー">
                                    <i className="bi bi-files"></i>
                                  </button>
                                  <button type="button" className="memo-item__action" onClick={() => startQuickEdit(memo)} disabled={isBusy} title="タイトル・タグを編集">
                                    <i className="bi bi-pencil-square"></i>
                                  </button>
                                  <button type="button" className={`memo-item__action${memo.is_pinned ? " is-active" : ""}`} onClick={() => { void handleTogglePin(memo); }} disabled={isBusy} title={memo.is_pinned ? "ピン留め解除" : "ピン留め"}>
                                    <i className="bi bi-pin-angle"></i>
                                  </button>
                                  <button type="button" className={`memo-item__action${memo.is_archived ? " is-active" : ""}`} onClick={() => { void handleToggleArchive(memo); }} disabled={isBusy} title={memo.is_archived ? "アーカイブ解除" : "アーカイブ"}>
                                    <i className="bi bi-archive"></i>
                                  </button>
                                  <button type="button" className="memo-item__action" onClick={() => { void openShareModal(memo); }} disabled={isBusy} title="共有設定">
                                    <i className="bi bi-share"></i>
                                  </button>
                                  <button type="button" className="memo-item__action memo-item__action--danger" onClick={() => { void handleDeleteMemo(memo); }} disabled={isBusy} title="削除">
                                    <i className="bi bi-trash3"></i>
                                  </button>
                                </div>
                              )}
                            </>
                          )}
                        </article>
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>

            {/* ── Compose panel ── */}
            <section className="memo-card memo-compose-panel">
              <div className="memo-panel__header">
                <h2>新規メモ</h2>
                <p>AI回答は必須、他は必要に応じて入力してください。</p>
              </div>

              <form method="post" className="memo-form" onSubmit={handleSubmitMemo}>
                <div className="form-group">
                  <label htmlFor="input_content">入力内容 <span className="optional">(任意)</span></label>
                  <textarea id="input_content" name="input_content" className="memo-control" value={formState.input_content} onChange={handleFormChange} placeholder="AIに送った入力内容" />
                </div>

                <div className="form-group">
                  <div className="memo-response-header">
                    <label htmlFor="ai_response">AIの回答</label>
                    <div className="memo-response-tabs">
                      <button type="button" className={`memo-response-tab${!previewMode ? " is-active" : ""}`} onClick={() => setPreviewMode(false)}>
                        <i className="bi bi-code-slash"></i>編集
                      </button>
                      <button type="button" className={`memo-response-tab${previewMode ? " is-active" : ""}`} onClick={() => setPreviewMode(true)} disabled={!formState.ai_response.trim()}>
                        <i className="bi bi-eye"></i>プレビュー
                      </button>
                    </div>
                  </div>
                  {previewMode ? (
                    <div className="memo-preview-pane">
                      {formState.ai_response.trim()
                        ? <MemoMarkdown text={parseMemoText(formState.ai_response)} className="memo-preview-content" />
                        : <p className="memo-preview-empty">プレビューするテキストがありません。</p>}
                    </div>
                  ) : (
                    <textarea
                      id="ai_response"
                      name="ai_response"
                      className="memo-control memo-control--response"
                      value={formState.ai_response}
                      onChange={handleFormChange}
                      placeholder="AIからの回答"
                      required
                    />
                  )}
                </div>

                <div className="form-grid">
                  <div className="form-group">
                    <div className="memo-field-header">
                      <label htmlFor="title">タイトル <span className="optional">(任意)</span></label>
                      <button
                        type="button"
                        className={`memo-ai-suggest-btn${aiSuggesting ? " is-loading" : ""}`}
                        onClick={() => { void handleAiSuggest(); }}
                        disabled={aiSuggesting || !formState.ai_response.trim()}
                        title="AIがタイトルとタグを提案"
                      >
                        {aiSuggesting
                          ? <><i className="bi bi-arrow-repeat memo-spin"></i>提案中…</>
                          : <><i className="bi bi-stars"></i>AI提案</>}
                      </button>
                    </div>
                    <input
                      id="title"
                      name="title"
                      type="text"
                      className="memo-control"
                      value={formState.title}
                      onChange={handleFormChange}
                      maxLength={255}
                      placeholder="空欄なら回答1行目を採用"
                    />
                  </div>
                  <div className="form-group">
                    <label htmlFor="tags">タグ <span className="optional">(任意)</span></label>
                    <input id="tags" name="tags" type="text" className="memo-control" value={formState.tags} onChange={handleFormChange} maxLength={255} placeholder="例: 設計 仕様" />
                  </div>
                </div>

                {collections.length > 0 && (
                  <div className="form-group">
                    <label htmlFor="compose_collection">コレクション <span className="optional">(任意)</span></label>
                    <select id="compose_collection" name="collection_id" className="memo-control" value={formState.collection_id ?? ""} onChange={handleFormChange}>
                      <option value="">コレクションなし</option>
                      {collections.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                    </select>
                  </div>
                )}

                <div className="form-actions">
                  <button type="submit" className="primary-button" disabled={submitting}>
                    <i className="bi bi-save"></i>
                    保存する
                  </button>
                </div>
              </form>
            </section>
          </div>
        </div>

        {/* ── Memo detail modal ── */}
        <div className={`memo-modal${selectedMemo ? " is-visible" : ""}`} aria-hidden={selectedMemo ? "false" : "true"}>
          <div className="memo-modal__overlay" onClick={() => setSelectedMemo(null)}></div>
          <div className="memo-modal__content" role="dialog" aria-modal="true" aria-labelledby="memoModalTitle">
            <button type="button" className="memo-modal__close" aria-label="閉じる" onClick={() => setSelectedMemo(null)}>
              <i className="bi bi-x-lg"></i>
            </button>
            <header className="memo-modal__header">
              <h3 id="memoModalTitle">{selectedMemo?.title || "保存したメモ"}</h3>
              <p className="memo-modal__date">{formatDateTime(selectedMemo?.updated_at || selectedMemo?.created_at) || selectedMemo?.created_at || ""}</p>
            </header>
            {detailLoading && <div className="memo-history__empty"><InlineLoading label="メモを読み込んでいます..." className="mx-auto" /></div>}
            {!detailLoading && detailError && <div className="memo-history__empty">{detailError}</div>}
            {!detailLoading && selectedMemo && (
              <>
                <div className="memo-modal__tags">
                  {selectedMemo.collection_name && <CollectionBadge name={selectedMemo.collection_name} color={selectedMemo.collection_color || "#6b7280"} />}
                  {splitTags(selectedMemo.tags).length
                    ? splitTags(selectedMemo.tags).map((tag) => <span className="memo-tag" key={tag}>{tag}</span>)
                    : <span className="memo-tag memo-tag--muted">タグなし</span>}
                </div>
                <div className="memo-modal__body">
                  {selectedMemo.input_content && (
                    <section className="memo-modal__section">
                      <h4>入力内容</h4>
                      <MemoMarkdown text={parseMemoText(selectedMemo.input_content)} className="memo-modal__markdown" />
                    </section>
                  )}
                  <section className={`memo-modal__section${!selectedMemo.input_content ? " memo-modal__section--full" : ""}`}>
                    <h4>AIの回答</h4>
                    <MemoMarkdown text={parseMemoText(selectedMemo.ai_response)} className="memo-modal__markdown" />
                  </section>
                </div>
              </>
            )}
          </div>
        </div>

        {/* ── Share modal ── */}
        <div className={`memo-share-modal${isShareModalOpen ? " is-visible" : ""}`} aria-hidden={isShareModalOpen ? "false" : "true"}>
          <div className="memo-share-modal__overlay" onClick={closeShareModal}></div>
          <div className="memo-share-modal__content" role="dialog" aria-modal="true" aria-labelledby="memoShareTitle">
            <button type="button" className="memo-share-modal__close" aria-label="閉じる" onClick={closeShareModal}>
              <i className="bi bi-x-lg"></i>
            </button>
            <header className="memo-share-modal__header">
              <h3 id="memoShareTitle">共有設定: {shareMemoTitle}</h3>
              <p>リンク作成・期限設定・無効化をここで管理できます。</p>
            </header>
            <div className="memo-share-modal__body">
              <div className="memo-share-modal__row">
                <label htmlFor="memo-share-link-input">共有リンク</label>
                <input id="memo-share-link-input" type="text" readOnly value={shareUrl} placeholder="共有リンクを作成してください" />
              </div>
              <div className="memo-share-modal__row">
                <label htmlFor="memo-share-expiry">有効期限</label>
                <select
                  id="memo-share-expiry"
                  value={shareExpiry}
                  onChange={(e) => setShareExpiry(e.target.value as (typeof SHARE_EXPIRES_OPTIONS)[number]["value"])}
                  disabled={shareLoading}
                >
                  {SHARE_EXPIRES_OPTIONS.map((opt) => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
                </select>
              </div>
              <div className="memo-share-modal__actions">
                <button type="button" className="primary-button" onClick={() => { void createShareLink(false); }} disabled={shareLoading}><i className="bi bi-link-45deg"></i>作成</button>
                <button type="button" className="secondary-button" onClick={() => { void createShareLink(true); }} disabled={shareLoading}><i className="bi bi-arrow-repeat"></i>再生成</button>
                <button type="button" className="secondary-button" onClick={() => { void revokeShareLink(); }} disabled={shareLoading}><i className="bi bi-slash-circle"></i>無効化</button>
                <button type="button" className="secondary-button" onClick={() => { void copyShareLink(); }} disabled={shareLoading || !shareUrl}><i className="bi bi-files"></i>コピー</button>
                {supportsNativeShare && (
                  <button type="button" className="secondary-button" onClick={() => { void openNativeShareSheet(); }} disabled={shareLoading || !shareUrl}><i className="bi bi-box-arrow-up-right"></i>端末共有</button>
                )}
              </div>
              {shareStatus && <p className={`memo-share-modal__status memo-share-modal__status--${shareStatus.type}`}>{shareStatus.text}</p>}
              <div className="memo-share-modal__meta">
                <span>{shareState?.is_active ? "公開中" : "未公開 / 無効"}</span>
                <span>{shareState?.expires_at ? `期限: ${formatDateTime(shareState.expires_at) || shareState.expires_at}` : "期限: 無期限"}</span>
              </div>
              <div className="memo-share-modal__sns">
                <a target="_blank" rel="noopener noreferrer" href={shareSnsLinks.x}><span>X</span></a>
                <a target="_blank" rel="noopener noreferrer" href={shareSnsLinks.line}><span>LINE</span></a>
                <a target="_blank" rel="noopener noreferrer" href={shareSnsLinks.facebook}><span>Facebook</span></a>
              </div>
            </div>
          </div>
        </div>

        {/* ── Collection management panel ── */}
        <div className={`memo-collection-modal${isCollectionPanelOpen ? " is-visible" : ""}`} aria-hidden={isCollectionPanelOpen ? "false" : "true"}>
          <div className="memo-collection-modal__overlay" onClick={() => setIsCollectionPanelOpen(false)}></div>
          <div className="memo-collection-modal__content" role="dialog" aria-modal="true" aria-labelledby="collectionPanelTitle">
            <button type="button" className="memo-collection-modal__close" aria-label="閉じる" onClick={() => setIsCollectionPanelOpen(false)}>
              <i className="bi bi-x-lg"></i>
            </button>
            <header className="memo-collection-modal__header">
              <h3 id="collectionPanelTitle"><i className="bi bi-folder2-open"></i>コレクション管理</h3>
              <p>メモをグループ分けして整理できます。</p>
            </header>
            <div className="memo-collection-modal__body">
              {/* Create new */}
              <div className="memo-collection-create">
                <input
                  type="text"
                  className="memo-control memo-collection-create__input"
                  value={newCollectionName}
                  onChange={(e) => setNewCollectionName(e.target.value)}
                  placeholder="新しいコレクション名"
                  maxLength={100}
                  onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void handleCreateCollection(); } }}
                />
                <div className="memo-collection-create__color-row">
                  <label htmlFor="new-collection-color">カラー</label>
                  <input type="color" id="new-collection-color" value={newCollectionColor} onChange={(e) => setNewCollectionColor(e.target.value)} className="memo-collection-color-input" />
                  <div className="memo-collection-presets">
                    {["#6b7280", "#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#0ea5e9"].map((c) => (
                      <button
                        type="button"
                        key={c}
                        className={`memo-collection-preset${newCollectionColor === c ? " is-active" : ""}`}
                        style={{ background: c }}
                        onClick={() => setNewCollectionColor(c)}
                        title={c}
                      />
                    ))}
                  </div>
                </div>
                <button
                  type="button"
                  className="primary-button memo-collection-create__btn"
                  onClick={() => { void handleCreateCollection(); }}
                  disabled={collectionActionLoading || !newCollectionName.trim()}
                >
                  <i className="bi bi-plus-lg"></i>作成
                </button>
              </div>

              {/* Collection list */}
              {collections.length === 0 && <p className="memo-collection-empty">コレクションはまだありません。</p>}
              <ul className="memo-collection-list">
                {collections.map((col) => (
                  <li key={col.id} className="memo-collection-item">
                    {editingCollectionId === col.id ? (
                      <div className="memo-collection-item__edit">
                        <input
                          type="text"
                          className="memo-control"
                          value={editingCollectionName}
                          onChange={(e) => setEditingCollectionName(e.target.value)}
                          maxLength={100}
                        />
                        <div className="memo-collection-create__color-row">
                          <label>カラー</label>
                          <input type="color" value={editingCollectionColor} onChange={(e) => setEditingCollectionColor(e.target.value)} className="memo-collection-color-input" />
                          <div className="memo-collection-presets">
                            {["#6b7280", "#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#0ea5e9"].map((c) => (
                              <button type="button" key={c} className={`memo-collection-preset${editingCollectionColor === c ? " is-active" : ""}`} style={{ background: c }} onClick={() => setEditingCollectionColor(c)} title={c} />
                            ))}
                          </div>
                        </div>
                        <div className="memo-collection-item__edit-actions">
                          <button type="button" className="primary-button" onClick={() => { void handleUpdateCollection(col.id); }} disabled={collectionActionLoading}>保存</button>
                          <button type="button" className="secondary-button" onClick={() => setEditingCollectionId(null)}>キャンセル</button>
                        </div>
                      </div>
                    ) : (
                      <div className="memo-collection-item__row">
                        <span className="memo-collection-item__dot" style={{ background: col.color }}></span>
                        <span className="memo-collection-item__name">{col.name}</span>
                        <span className="memo-collection-item__count">{col.memo_count}件</span>
                        <button type="button" className="memo-collection-item__action" onClick={() => { setEditingCollectionId(col.id); setEditingCollectionName(col.name); setEditingCollectionColor(col.color); }} title="編集">
                          <i className="bi bi-pencil"></i>
                        </button>
                        <button type="button" className="memo-collection-item__action memo-collection-item__action--danger" onClick={() => { void handleDeleteCollection(col.id, col.name); }} disabled={collectionActionLoading} title="削除">
                          <i className="bi bi-trash3"></i>
                        </button>
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>

        {/* ── Export modal ── */}
        <div className={`memo-export-modal${isExportModalOpen ? " is-visible" : ""}`} aria-hidden={isExportModalOpen ? "false" : "true"}>
          <div className="memo-export-modal__overlay" onClick={() => setIsExportModalOpen(false)}></div>
          <div className="memo-export-modal__content" role="dialog" aria-modal="true" aria-labelledby="exportModalTitle">
            <button type="button" className="memo-export-modal__close" aria-label="閉じる" onClick={() => setIsExportModalOpen(false)}>
              <i className="bi bi-x-lg"></i>
            </button>
            <header className="memo-export-modal__header">
              <h3 id="exportModalTitle"><i className="bi bi-download"></i>メモをエクスポート</h3>
              <p>保存したメモをファイルとしてダウンロードします。</p>
            </header>
            <div className="memo-export-modal__body">
              <div className="memo-export-section">
                <p className="memo-export-label">フォーマット</p>
                <div className="memo-export-formats">
                  {EXPORT_FORMATS.map((fmt) => (
                    <label
                      key={fmt.value}
                      className={`memo-export-format-option${exportFormat === fmt.value ? " is-active" : ""}`}
                    >
                      <input
                        type="radio"
                        name="export-format"
                        value={fmt.value}
                        checked={exportFormat === fmt.value}
                        onChange={() => setExportFormat(fmt.value as typeof exportFormat)}
                        className="sr-only"
                      />
                      <i className={`bi ${fmt.icon}`}></i>
                      <span>{fmt.label}</span>
                    </label>
                  ))}
                </div>
              </div>
              <div className="memo-export-section">
                <p className="memo-export-label">対象範囲</p>
                <div className="memo-export-scope">
                  <label className={`memo-export-scope-option${exportScope === "all" ? " is-active" : ""}`}>
                    <input type="radio" name="export-scope" value="all" checked={exportScope === "all"} onChange={() => setExportScope("all")} className="sr-only" />
                    <i className="bi bi-collection"></i>すべてのメモ
                  </label>
                  <label className={`memo-export-scope-option${exportScope === "selected" ? " is-active" : ""}${selectedIds.size === 0 ? " is-disabled" : ""}`}>
                    <input type="radio" name="export-scope" value="selected" checked={exportScope === "selected"} onChange={() => setExportScope("selected")} disabled={selectedIds.size === 0} className="sr-only" />
                    <i className="bi bi-check2-square"></i>
                    {selectedIds.size > 0 ? `選択中の${selectedIds.size}件` : "選択したメモ（未選択）"}
                  </label>
                </div>
              </div>
              <div className="memo-export-actions">
                <button type="button" className="primary-button" onClick={handleExport}>
                  <i className="bi bi-download"></i>ダウンロード
                </button>
                <button type="button" className="secondary-button" onClick={() => setIsExportModalOpen(false)}>キャンセル</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
