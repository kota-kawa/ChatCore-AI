import { SeoHead } from "../components/SeoHead";
import { useRouter } from "next/router";
import {
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
import { createPortal } from "react-dom";
import useSWR from "swr";

import "../scripts/core/csrf";
import { InlineLoading } from "../components/ui/inline_loading";
import { formatDateTime } from "../lib/datetime";
import { formatLLMOutput } from "../scripts/chat/chat_ui";
import { copyTextToClipboard, renderSanitizedHTML } from "../scripts/chat/message_utils";
import { setLoggedInState } from "../scripts/core/app_state";
import { fetchJsonOrThrow } from "../scripts/core/runtime_validation";
import { showConfirmModal } from "../scripts/core/alert_modal";

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
type DetailSaveStatus = "idle" | "saving" | "saved" | "error";
type BulkAction = "delete" | "archive" | "unarchive" | "pin" | "unpin" | "set_collection" | "clear_collection";
type MemoActionMenuPosition = { top: number; left: number; width: number; maxHeight: number };
type MemoDropPosition = "before" | "after";
type MemoCollectionDropTarget = number | "none" | "";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DEFAULT_LIMIT = 50;
const MEMO_ACTION_MENU_WIDTH = 168;
const MEMO_ACTION_MENU_ESTIMATED_HEIGHT = 172;
const MEMO_ACTION_MENU_GAP = 6;
const MEMO_ACTION_MENU_VIEWPORT_MARGIN = 8;
const MEMO_SHARE_TITLE = "Chat Core 共有メモ";
const MEMO_SHARE_TEXT = "このメモを共有しました。";
const DETAIL_AUTOSAVE_DELAY_MS = 900;
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

function buildMemoListUrl(options: {
  query: string;
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
  if (tq) params.set("q", tq);
  if (options.archiveScope === "all") params.set("include_archived", "1");
  else if (options.archiveScope === "archived") params.set("only_archived", "1");
  if (options.collectionId !== null) params.set("collection_id", String(options.collectionId));

  return `/memo/api/recent?${params.toString()}`;
}

function getMemoActionMenuPosition(trigger: HTMLElement): MemoActionMenuPosition {
  const rect = trigger.getBoundingClientRect();
  const viewportWidth = window.innerWidth;
  const viewportHeight = window.innerHeight;
  const width = MEMO_ACTION_MENU_WIDTH;
  const left = Math.min(
    Math.max(MEMO_ACTION_MENU_VIEWPORT_MARGIN, rect.right - width),
    Math.max(MEMO_ACTION_MENU_VIEWPORT_MARGIN, viewportWidth - width - MEMO_ACTION_MENU_VIEWPORT_MARGIN),
  );
  const spaceAbove = rect.top - MEMO_ACTION_MENU_VIEWPORT_MARGIN;
  const spaceBelow = viewportHeight - rect.bottom - MEMO_ACTION_MENU_VIEWPORT_MARGIN;
  const openBelow = spaceBelow >= MEMO_ACTION_MENU_ESTIMATED_HEIGHT || spaceBelow >= spaceAbove;
  const availableHeight = Math.max(
    120,
    (openBelow ? spaceBelow : spaceAbove) - MEMO_ACTION_MENU_GAP,
  );
  const top = openBelow
    ? Math.min(rect.bottom + MEMO_ACTION_MENU_GAP, viewportHeight - MEMO_ACTION_MENU_VIEWPORT_MARGIN - availableHeight)
    : Math.max(MEMO_ACTION_MENU_VIEWPORT_MARGIN, rect.top - MEMO_ACTION_MENU_GAP - Math.min(MEMO_ACTION_MENU_ESTIMATED_HEIGHT, availableHeight));
  return { top, left, width, maxHeight: availableHeight };
}

function getMemoSectionKey(memo: MemoSummary) {
  return `${memo.is_pinned ? "pinned" : "other"}:${memo.is_archived ? "archived" : "active"}`;
}

function computeProjectedSectionOrder(
  memos: MemoSummary[],
  draggedId: string,
  targetId: string,
  position: MemoDropPosition,
): string[] | null {
  if (!draggedId || !targetId || draggedId === targetId) return null;
  const draggedMemo = memos.find((memo) => String(memo.id) === draggedId);
  const targetMemo = memos.find((memo) => String(memo.id) === targetId);
  if (!draggedMemo || !targetMemo) return null;
  const sectionKey = getMemoSectionKey(draggedMemo);
  if (getMemoSectionKey(targetMemo) !== sectionKey) return null;

  const section = memos.filter((memo) => getMemoSectionKey(memo) === sectionKey);
  const without = section.filter((memo) => String(memo.id) !== draggedId);
  const targetIdx = without.findIndex((memo) => String(memo.id) === targetId);
  if (targetIdx < 0) return null;
  const insertIdx = position === "before" ? targetIdx : targetIdx + 1;
  const next = [...without];
  next.splice(insertIdx, 0, draggedMemo);
  return next.map((memo) => String(memo.id));
}

function computeProjectedSectionOrderFromPoint(
  memos: MemoSummary[],
  sectionMemos: MemoSummary[],
  draggedId: string,
  clientX: number,
  clientY: number,
  cardRefs: Map<string, HTMLElement>,
): string[] | null {
  const draggedMemo = memos.find((memo) => String(memo.id) === draggedId);
  if (!draggedMemo) return null;
  const sectionKey = getMemoSectionKey(sectionMemos[0] || draggedMemo);
  if (getMemoSectionKey(draggedMemo) !== sectionKey) return null;

  const section = memos.filter((memo) => getMemoSectionKey(memo) === sectionKey);
  const without = section.filter((memo) => String(memo.id) !== draggedId);
  if (without.length === 0) return section.map((memo) => String(memo.id));

  let bestMemo: MemoSummary | null = null;
  let bestDistance = Number.POSITIVE_INFINITY;
  for (const memo of without) {
    const element = cardRefs.get(String(memo.id));
    if (!element) continue;
    const rect = element.getBoundingClientRect();
    const dx = clientX < rect.left ? rect.left - clientX : clientX > rect.right ? clientX - rect.right : 0;
    const dy = clientY < rect.top ? rect.top - clientY : clientY > rect.bottom ? clientY - rect.bottom : 0;
    const distance = dx * dx + dy * dy;
    if (distance < bestDistance) {
      bestDistance = distance;
      bestMemo = memo;
    }
  }
  if (!bestMemo) return null;

  const targetElement = cardRefs.get(String(bestMemo.id));
  const targetRect = targetElement?.getBoundingClientRect();
  const position: MemoDropPosition =
    targetRect && clientY < targetRect.top + targetRect.height / 2 ? "before" : "after";
  return computeProjectedSectionOrder(memos, draggedId, String(bestMemo.id), position);
}

function applySectionProjection(memos: MemoSummary[], projection: string[] | null): MemoSummary[] {
  if (!projection || projection.length === 0) return memos;
  const projectedSet = new Set(projection);
  const idToMemo = new Map(memos.map((memo) => [String(memo.id), memo]));
  const result: MemoSummary[] = [];
  let projIdx = 0;
  for (const memo of memos) {
    if (projectedSet.has(String(memo.id))) {
      while (projIdx < projection.length) {
        const m = idToMemo.get(projection[projIdx++]);
        if (m) {
          result.push(m);
          break;
        }
      }
    } else {
      result.push(memo);
    }
  }
  return result;
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
// MemoSelect – custom styled dropdown
// ---------------------------------------------------------------------------

type SelectOption = { value: string; label: string };

function MemoSelect({
  value,
  onChange,
  options,
  className,
  disabled,
  id,
}: {
  value: string;
  onChange: (value: string) => void;
  options: SelectOption[];
  className?: string;
  disabled?: boolean;
  id?: string;
}) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number; width: number } | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLUListElement>(null);

  const toggleOpen = () => {
    if (disabled) return;
    if (!open && triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect();
      setPos({ top: rect.bottom + 6, left: rect.left, width: rect.width });
    }
    setOpen((v) => !v);
  };

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!triggerRef.current?.contains(e.target as Node) && !menuRef.current?.contains(e.target as Node))
        setOpen(false);
    };
    const onScroll = () => setOpen(false);
    document.addEventListener("mousedown", onDown);
    window.addEventListener("scroll", onScroll, true);
    return () => {
      document.removeEventListener("mousedown", onDown);
      window.removeEventListener("scroll", onScroll, true);
    };
  }, [open]);

  const selectedLabel = options.find((o) => o.value === value)?.label ?? "";

  return (
    <div
      id={id}
      className={`memo-select${open ? " is-open" : ""}${disabled ? " is-disabled" : ""}${className ? ` ${className}` : ""}`}
    >
      <button
        ref={triggerRef}
        type="button"
        className="memo-select__trigger"
        onClick={toggleOpen}
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <span className="memo-select__label">{selectedLabel}</span>
        <i className="bi bi-chevron-down memo-select__chevron" aria-hidden="true" />
      </button>
      {open && pos && createPortal(
        <ul
          ref={menuRef}
          className="memo-select__menu"
          role="listbox"
          style={{ position: "fixed", top: pos.top, left: pos.left, minWidth: pos.width, zIndex: 99999 }}
        >
          {options.map((opt) => {
            const isSel = opt.value === value;
            return (
              <li
                key={opt.value}
                role="option"
                aria-selected={isSel}
                className={`memo-select__option${isSel ? " is-selected" : ""}`}
                onClick={() => { onChange(opt.value); setOpen(false); }}
              >
                {isSel && <i className="bi bi-check2 memo-select__check" aria-hidden="true" />}
                {opt.label}
              </li>
            );
          })}
        </ul>,
        document.body,
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function MemoPage() {
  const router = useRouter();

  // Form state
  const [formState, setFormState] = useState({
    ai_response: "",
    title: "",
    collection_id: null as number | null,
  });
  const [previewMode, setPreviewMode] = useState(false);
  const [flashState, setFlashState] = useState<FlashState | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [aiSuggesting, setAiSuggesting] = useState(false);
  const [isLoggedIn, setIsLoggedIn] = useState(false);

  // Filter/sort state
  const [query, setQuery] = useState("");
  const [sortMode, setSortMode] = useState("manual");
  const [archiveScope, setArchiveScope] = useState("active");
  const [activeCollectionId, setActiveCollectionId] = useState<number | null>(null);

  // Keep-style board state
  const [isComposeExpanded, setIsComposeExpanded] = useState(false);
  const [viewMode, setViewMode] = useState<"grid" | "list">("grid");

  // Detail modal
  const [selectedMemo, setSelectedMemo] = useState<MemoDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [detailPreviewMode, setDetailPreviewMode] = useState(true);
  const [detailMetaOpen, setDetailMetaOpen] = useState(false);
  const [detailEditTitle, setDetailEditTitle] = useState("");
  const [detailEditCollectionId, setDetailEditCollectionId] = useState<number | null>(null);
  const [detailEditAiResponse, setDetailEditAiResponse] = useState("");
  const [detailSaveStatus, setDetailSaveStatus] = useState<DetailSaveStatus>("idle");
  const [detailSaveError, setDetailSaveError] = useState("");
  const detailAutoSaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const detailSaveSequenceRef = useRef(0);
  const detailEditSnapshotRef = useRef({
    title: "",
    collectionId: null as number | null,
    aiResponse: "",
  });

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
  const [draggedMemoId, setDraggedMemoId] = useState<string>("");
  const [dragProjectedOrder, setDragProjectedOrder] = useState<string[] | null>(null);
  const [dragCollectionTarget, setDragCollectionTarget] = useState<MemoCollectionDropTarget>("");
  const [dragSaving, setDragSaving] = useState(false);
  const cardRefs = useRef<Map<string, HTMLElement>>(new Map());
  const cardPositionsRef = useRef<Map<string, DOMRect>>(new Map());

  // Export modal
  const [isExportModalOpen, setIsExportModalOpen] = useState(false);
  const [exportFormat, setExportFormat] = useState<"markdown" | "json" | "csv">("markdown");
  const [exportScope, setExportScope] = useState<"all" | "selected">("all");

  // -----------------------------------------------------------------------
  // Data fetching
  // -----------------------------------------------------------------------

  const listUrl = useMemo(
    () => buildMemoListUrl({ query, sort: sortMode, archiveScope, collectionId: activeCollectionId }),
    [archiveScope, query, sortMode, activeCollectionId],
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
    if (selectedMemo) return;
    if (detailAutoSaveTimerRef.current) {
      clearTimeout(detailAutoSaveTimerRef.current);
      detailAutoSaveTimerRef.current = null;
    }
    detailSaveSequenceRef.current += 1;
    setDetailPreviewMode(true);
    setDetailMetaOpen(false);
    setDetailEditTitle("");
    setDetailEditCollectionId(null);
    setDetailEditAiResponse("");
    setDetailSaveStatus("idle");
    setDetailSaveError("");
  }, [selectedMemo]);

  useEffect(() => {
    detailEditSnapshotRef.current = {
      title: detailEditTitle,
      collectionId: detailEditCollectionId,
      aiResponse: detailEditAiResponse,
    };
  }, [detailEditAiResponse, detailEditCollectionId, detailEditTitle]);

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

  // -----------------------------------------------------------------------
  // Helpers
  // -----------------------------------------------------------------------

  const showFlash = useCallback((type: "success" | "error", text: string) => {
    setFlashState({ type, text });
    setTimeout(() => setFlashState(null), 4000);
  }, []);

  const canDragMemos =
    archiveScope === "active" &&
    !isBulkMode &&
    !dragSaving &&
    (collections.length > 0 || (sortMode === "manual" && !query.trim()));
  const canReorderCurrentView =
    canDragMemos &&
    sortMode === "manual" &&
    !query.trim();

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
      setFormState({ ai_response: "", title: "", collection_id: null });
      setPreviewMode(false);
      setIsComposeExpanded(false);
      showFlash("success", "メモを保存しました。");
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
      const { payload } = await fetchJsonOrThrow<{ title?: string }>(
        "/memo/api/suggest",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ ai_response: formState.ai_response }),
        },
        { defaultMessage: "AI提案の取得に失敗しました。" },
      );
      setFormState((prev) => ({
        ...prev,
        title: payload.title || prev.title,
      }));
      showFlash("success", "AIがタイトルを提案しました。");
    } catch (error) {
      showFlash("error", error instanceof Error ? error.message : "AI提案に失敗しました。");
    } finally {
      setAiSuggesting(false);
    }
  }, [formState.ai_response, showFlash]);

  // -----------------------------------------------------------------------
  // Memo detail
  // -----------------------------------------------------------------------

  const detailHasUnsavedChanges = useMemo(() => {
    if (!selectedMemo) return false;
    return (
      detailEditTitle !== (selectedMemo.title || "") ||
      detailEditCollectionId !== (selectedMemo.collection_id ?? null) ||
      detailEditAiResponse !== (selectedMemo.ai_response || "")
    );
  }, [
    detailEditAiResponse,
    detailEditCollectionId,
    detailEditTitle,
    selectedMemo,
  ]);

  const clearDetailAutoSaveTimer = useCallback(() => {
    if (!detailAutoSaveTimerRef.current) return;
    clearTimeout(detailAutoSaveTimerRef.current);
    detailAutoSaveTimerRef.current = null;
  }, []);

  const openMemoDetail = useCallback(async (memoId: string | number) => {
    setDetailError("");
    setDetailLoading(true);
    setDetailPreviewMode(true);
    setDetailMetaOpen(false);
    setDetailSaveStatus("idle");
    setDetailSaveError("");
    if (detailAutoSaveTimerRef.current) {
      clearTimeout(detailAutoSaveTimerRef.current);
      detailAutoSaveTimerRef.current = null;
    }
    detailSaveSequenceRef.current += 1;
    try {
      const memo = await loadMemoDetail(memoId);
      if (!memo) { setDetailError("メモの詳細を取得できませんでした。"); return; }
      setDetailEditTitle(memo.title || "");
      setDetailEditCollectionId(memo.collection_id ?? null);
      setDetailEditAiResponse(memo.ai_response || "");
      setSelectedMemo(memo);
      setDetailSaveStatus("saved");
    } catch (error) {
      setDetailError(error instanceof Error ? error.message : "メモの詳細取得に失敗しました。");
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const saveDetailEdit = useCallback(async () => {
    if (!selectedMemo?.id || !detailHasUnsavedChanges) return true;
    if (!detailEditAiResponse.trim()) {
      setDetailSaveStatus("error");
      setDetailSaveError("AIの回答を入力してください。");
      return false;
    }
    const snapshot = {
      title: detailEditTitle,
      collectionId: detailEditCollectionId,
      aiResponse: detailEditAiResponse,
    };
    const requestId = ++detailSaveSequenceRef.current;
    setDetailSaveStatus("saving");
    setDetailSaveError("");
    try {
      const body: Record<string, unknown> = {
        title: snapshot.title,
        ai_response: snapshot.aiResponse,
      };

      if (collections.length > 0) {
        if (snapshot.collectionId !== null) {
          body.collection_id = snapshot.collectionId;
        } else {
          body.clear_collection = true;
        }
      }

      const { payload } = await fetchJsonOrThrow<{ memo?: MemoDetail }>(
        `/memo/api/${selectedMemo.id}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify(body),
        },
        { defaultMessage: "メモ本文の更新に失敗しました。", hasApplicationError: (data) => !data.memo },
      );
      if (requestId === detailSaveSequenceRef.current) {
        if (payload.memo) {
          setSelectedMemo(payload.memo);
          const current = detailEditSnapshotRef.current;
          const fieldsStillMatchSavedSnapshot =
            current.title === snapshot.title &&
            current.collectionId === snapshot.collectionId &&
            current.aiResponse === snapshot.aiResponse;
          if (fieldsStillMatchSavedSnapshot) {
            setDetailEditTitle(payload.memo.title || "");
            setDetailEditCollectionId(payload.memo.collection_id ?? null);
            setDetailEditAiResponse(payload.memo.ai_response || "");
          }
        }
        setDetailSaveStatus("saved");
        setDetailSaveError("");
      }
      void mutate();
      return true;
    } catch (error) {
      if (requestId === detailSaveSequenceRef.current) {
        setDetailSaveStatus("error");
        setDetailSaveError(error instanceof Error ? error.message : "メモ本文の更新に失敗しました。");
      }
      return false;
    }
  }, [
    collections.length,
    detailEditAiResponse,
    detailEditCollectionId,
    detailEditTitle,
    detailHasUnsavedChanges,
    mutate,
    selectedMemo?.id,
  ]);

  const closeMemoDetail = useCallback(async () => {
    clearDetailAutoSaveTimer();
    if (detailHasUnsavedChanges && detailEditAiResponse.trim()) {
      const saved = await saveDetailEdit();
      if (!saved) return;
    }
    setSelectedMemo(null);
  }, [clearDetailAutoSaveTimer, detailEditAiResponse, detailHasUnsavedChanges, saveDetailEdit]);

  useEffect(() => {
    clearDetailAutoSaveTimer();
    if (!selectedMemo || !detailHasUnsavedChanges) return;
    if (!detailEditAiResponse.trim()) {
      setDetailSaveStatus("error");
      setDetailSaveError("AIの回答を入力してください。");
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
    const confirmed = await showConfirmModal(`「${memo.title || "保存したメモ"}」を削除しますか？`);
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

  const copyMemoExcerpt = useCallback(async (memo: MemoSummary) => {
    const content = `${memo.title || "保存したメモ"}\n\n${parseMemoText(memo.excerpt)}`;
    try {
      await copyTextToClipboard(content.trim());
      const memoId = String(memo.id);
      setCopiedMemoId(memoId);
      setTimeout(() => {
        setCopiedMemoId((current) => (current === memoId ? "" : current));
      }, 1400);
    } catch (error) { showFlash("error", error instanceof Error ? error.message : "コピーに失敗しました。"); }
  }, [showFlash]);

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
    setDragCollectionTarget("");
  }, []);

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
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", memoId);
  }, [canDragMemos]);

  const handleMemoSectionDragOver = useCallback((event: DragEvent<HTMLUListElement>, sectionMemos: MemoSummary[]) => {
    if (!canReorderCurrentView || !draggedMemoId || sectionMemos.length === 0) return;
    const draggedMemo = displayMemos.find((memo) => String(memo.id) === draggedMemoId);
    if (!draggedMemo || getMemoSectionKey(draggedMemo) !== getMemoSectionKey(sectionMemos[0])) return;

    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    const nextOrder = computeProjectedSectionOrderFromPoint(
      displayMemos,
      sectionMemos,
      draggedMemoId,
      event.clientX,
      event.clientY,
      cardRefs.current,
    );
    if (!nextOrder) return;
    setDragProjectedOrder((prev) => {
      if (prev && prev.length === nextOrder.length && prev.every((id, i) => id === nextOrder[i])) {
        return prev;
      }
      return nextOrder;
    });
  }, [canReorderCurrentView, displayMemos, draggedMemoId]);

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
      showFlash("error", "並べ替え対象のメモIDが不正です。");
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
      await fetchJsonOrThrow(
        "/memo/api/reorder",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ memo_id: memoId, before_id: beforeId, after_id: afterId }),
        },
        { defaultMessage: "メモの並べ替えに失敗しました。" },
      );
      await mutate();
    } catch (error) {
      showFlash("error", error instanceof Error ? error.message : "メモの並べ替えに失敗しました。");
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

  const handleCollectionDragOver = useCallback((
    event: DragEvent<HTMLElement>,
    target: MemoCollectionDropTarget,
  ) => {
    if (!canDragMemos || !draggedMemoId || target === "") return;
    const draggedMemo = memos.find((memo) => String(memo.id) === draggedMemoId);
    if (!draggedMemo) return;
    const targetCollectionId = target === "none" ? null : target;
    if ((draggedMemo.collection_id ?? null) === targetCollectionId) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    setDragCollectionTarget(target);
  }, [canDragMemos, draggedMemoId, memos]);

  const handleCollectionDragLeave = useCallback((event: DragEvent<HTMLElement>) => {
    const nextTarget = event.relatedTarget;
    if (nextTarget instanceof Node && event.currentTarget.contains(nextTarget)) return;
    setDragCollectionTarget("");
  }, []);

  const handleCollectionDrop = useCallback(async (
    event: DragEvent<HTMLElement>,
    target: MemoCollectionDropTarget,
  ) => {
    event.preventDefault();
    event.stopPropagation();
    const sourceId = draggedMemoId || event.dataTransfer.getData("text/plain");
    if (!sourceId || target === "") {
      clearMemoDragState();
      return;
    }

    const targetCollectionId = target === "none" ? null : target;
    const sourceMemo = memos.find((memo) => String(memo.id) === sourceId);
    if (!sourceMemo || (sourceMemo.collection_id ?? null) === targetCollectionId) {
      clearMemoDragState();
      return;
    }

    const memoId = Number(sourceId);
    if (!Number.isFinite(memoId)) {
      showFlash("error", "移動対象のメモIDが不正です。");
      clearMemoDragState();
      return;
    }

    setDragSaving(true);
    clearMemoDragState();
    try {
      const body: Record<string, unknown> =
        targetCollectionId === null ? { clear_collection: true } : { collection_id: targetCollectionId };
      await fetchJsonOrThrow(
        `/memo/api/${memoId}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify(body),
        },
        { defaultMessage: "メモの移動に失敗しました。" },
      );
      showFlash("success", "メモを移動しました。");
      if (selectedMemo?.id && String(selectedMemo.id) === sourceId) {
        const refreshed = await loadMemoDetail(sourceId);
        if (refreshed) setSelectedMemo(refreshed);
      }
      await Promise.all([mutate(), mutateCollections()]);
    } catch (error) {
      showFlash("error", error instanceof Error ? error.message : "メモの移動に失敗しました。");
      await mutate();
    } finally {
      setDragSaving(false);
    }
  }, [
    canDragMemos,
    clearMemoDragState,
    draggedMemoId,
    memos,
    mutate,
    mutateCollections,
    selectedMemo?.id,
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

  const executeBulkAction = useCallback(async (action: BulkAction, extra?: { collectionId?: number | null }) => {
    if (selectedIds.size === 0) return;
    setBulkLoading(true);
    try {
      const body: Record<string, unknown> = {
        action,
        memo_ids: Array.from(selectedIds).map(Number),
      };
      if (extra?.collectionId !== undefined) body.collection_id = extra.collectionId;

      await fetchJsonOrThrow(
        "/memo/api/bulk",
        { method: "POST", headers: { "Content-Type": "application/json" }, credentials: "same-origin", body: JSON.stringify(body) },
        { defaultMessage: "一括操作に失敗しました。" },
      );
      const labels: Record<BulkAction, string> = {
        delete: "削除", archive: "アーカイブ", unarchive: "アーカイブ解除",
        pin: "ピン留め", unpin: "ピン留め解除",
        set_collection: "コレクション設定", clear_collection: "コレクション解除",
      };
      showFlash("success", `${selectedIds.size}件を${labels[action]}しました。`);
      if (action === "delete") setSelectedIds(new Set());
      await mutate();
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
    return payload;
  }, []);

  const openShareModal = useCallback(async (memo: MemoSummary) => {
    const memoId = String(memo.id || "");
    if (!memoId) { showFlash("error", "共有対象のメモが見つかりません。"); return; }
    setIsShareModalOpen(true);
    setShareState(null);
    setShareStatus({ type: "success", text: "共有情報を読み込んでいます..." });
    setShareLoading(true);
    try {
      const payload = await loadShareState(memoId);
      if (payload.share_url && payload.is_active) {
        setShareStatus({ type: "success", text: "共有リンクを表示しています。" });
        return;
      }

      setShareStatus({ type: "success", text: "共有リンクを作成しています..." });
      const { payload: createdPayload } = await fetchJsonOrThrow<SharePayload>(
        `/memo/api/${memoId}/share`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ force_refresh: false, expires_in_days: 30 }),
        },
        { defaultMessage: "共有リンクの作成に失敗しました。" },
      );
      setShareState(createdPayload);
      setShareStatus({ type: "success", text: "共有リンクを作成しました。" });
      await mutate();
    } catch (error) {
      setShareStatus({ type: "error", text: error instanceof Error ? error.message : "共有情報の取得に失敗しました。" });
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
    const confirmed = await showConfirmModal(`「${name}」を削除しますか？\nコレクション内のメモはコレクションから外れます。`);
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
  const activeCollection = activeCollectionId !== null ? collections.find((c) => c.id === activeCollectionId) : null;
  const hasActiveFilters = Boolean(query.trim()) || sortMode !== "manual" || archiveScope !== "active" || activeCollectionId !== null;
  const hasComposeDraft = Boolean(formState.ai_response.trim() || formState.title.trim());
  const composeIsExpanded = isComposeExpanded || hasComposeDraft;

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
          className="memo-auth-bar"
          style={{ display: isLoggedIn ? "none" : "" }}
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
              <div className="memo-toolbar__brand">
                <span className="memo-toolbar__app-mark" aria-hidden="true">
                  <i className="bi bi-sticky"></i>
                </span>
                <div className="memo-toolbar__title">
                  <h1>メモ</h1>
                  <span className="memo-toolbar__count">
                    <i className="bi bi-journal-text" aria-hidden="true"></i>
                    {totalMemoCount}件
                  </span>
                </div>
              </div>
              <div className="memo-toolbar__actions">
                <button
                  type="button"
                  className="memo-toolbar__icon-btn"
                  onClick={() => setViewMode((current) => (current === "grid" ? "list" : "grid"))}
                  aria-label={viewMode === "grid" ? "リスト表示に切り替え" : "グリッド表示に切り替え"}
                  data-tooltip={viewMode === "grid" ? "リスト表示" : "グリッド表示"}
                  data-tooltip-placement="bottom"
                >
                  <i className={`bi ${viewMode === "grid" ? "bi-view-list" : "bi-grid-3x3-gap"}`} aria-hidden="true"></i>
                  <span className="sr-only">{viewMode === "grid" ? "リスト表示に切り替え" : "グリッド表示に切り替え"}</span>
                </button>
                <button
                  type="button"
                  className={`memo-toolbar__icon-btn${isBulkMode ? " is-active" : ""}`}
                  onClick={() => { if (isBulkMode) exitBulkMode(); else setIsBulkMode(true); }}
                  aria-label={isBulkMode ? "一括選択を終了" : "一括操作モード"}
                  data-tooltip={isBulkMode ? "一括選択を終了" : "一括操作モード"}
                  data-tooltip-placement="bottom"
                >
                  <i className={`bi ${isBulkMode ? "bi-check2-square" : "bi-ui-checks"}`} aria-hidden="true"></i>
                  <span className="sr-only">{isBulkMode ? "一括選択を終了" : "一括操作モード"}</span>
                </button>
                <button
                  type="button"
                  className="memo-toolbar__icon-btn"
                  onClick={() => setIsCollectionPanelOpen(true)}
                  aria-label="コレクション管理"
                  data-tooltip="コレクション管理"
                  data-tooltip-placement="bottom"
                >
                  <i className="bi bi-folder2-open" aria-hidden="true"></i>
                  <span className="sr-only">コレクション管理</span>
                </button>
                <button
                  type="button"
                  className="memo-toolbar__icon-btn"
                  onClick={() => setIsExportModalOpen(true)}
                  aria-label="エクスポート"
                  data-tooltip="エクスポート"
                  data-tooltip-placement="bottom"
                >
                  <i className="bi bi-download" aria-hidden="true"></i>
                  <span className="sr-only">エクスポート</span>
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
              {sortMode === "semantic" && (
                <span className="memo-search__badge" data-tooltip="AI類似検索" data-tooltip-placement="top">
                  <i className="bi bi-stars" aria-hidden="true"></i>
                  AI
                </span>
              )}
              {hasActiveFilters && (
                <button
                  type="button"
                  className="memo-toolbar__search-clear"
                  onClick={() => { setQuery(""); setArchiveScope("active"); setSortMode("manual"); setActiveCollectionId(null); }}
                  aria-label="検索と絞り込みをクリア"
                  data-tooltip="検索と絞り込みをクリア"
                  data-tooltip-placement="top"
                >
                  <i className="bi bi-x-lg" aria-hidden="true"></i>
                </button>
              )}
            </div>

            <div className="memo-toolbar__filters">
              <div className="memo-filter-chips" role="group" aria-label="表示範囲">
                <button
                  type="button"
                  className={`memo-filter-chip${archiveScope === "active" ? " is-active" : ""}`}
                  onClick={() => setArchiveScope("active")}
                  aria-pressed={archiveScope === "active"}
                >
                  <i className="bi bi-inbox" aria-hidden="true"></i>
                  通常
                </button>
                <button
                  type="button"
                  className={`memo-filter-chip${archiveScope === "all" ? " is-active" : ""}`}
                  onClick={() => setArchiveScope("all")}
                  aria-pressed={archiveScope === "all"}
                >
                  <i className="bi bi-collection" aria-hidden="true"></i>
                  すべて
                </button>
                <button
                  type="button"
                  className={`memo-filter-chip${archiveScope === "archived" ? " is-active" : ""}`}
                  onClick={() => setArchiveScope("archived")}
                  aria-pressed={archiveScope === "archived"}
                >
                  <i className="bi bi-archive" aria-hidden="true"></i>
                  アーカイブ
                </button>
              </div>
              <div className="memo-sort-control">
                <i className="bi bi-sort-down" aria-hidden="true"></i>
                <MemoSelect
                  value={sortMode}
                  onChange={(v) => setSortMode(v)}
                  options={[
                    { value: "manual", label: "手動順" },
                    { value: "recent", label: "新しい順" },
                    { value: "updated", label: "更新順" },
                    { value: "oldest", label: "古い順" },
                    { value: "title", label: "タイトル順" },
                    { value: "semantic", label: "AI類似検索" },
                  ]}
                />
              </div>
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
                {draggedMemoId && (
                  <button
                    type="button"
                    className={`memo-collection-chip memo-collection-chip--drop${dragCollectionTarget === "none" ? " is-drop-target" : ""}`}
                    onClick={() => setActiveCollectionId(null)}
                    onDragOver={(event) => handleCollectionDragOver(event, "none")}
                    onDragLeave={handleCollectionDragLeave}
                    onDrop={(event) => { void handleCollectionDrop(event, "none"); }}
                  >
                    <i className="bi bi-folder-x" aria-hidden="true"></i>
                    未分類
                  </button>
                )}
                {collections.map((col) => (
                  <button
                    type="button"
                    key={col.id}
                    className={`memo-collection-chip${activeCollectionId === col.id ? " is-active" : ""}${dragCollectionTarget === col.id ? " is-drop-target" : ""}`}
                    style={{ "--badge-color": col.color } as React.CSSProperties}
                    onClick={() => setActiveCollectionId((prev) => (prev === col.id ? null : col.id))}
                    onDragOver={(event) => handleCollectionDragOver(event, col.id)}
                    onDragLeave={handleCollectionDragLeave}
                    onDrop={(event) => { void handleCollectionDrop(event, col.id); }}
                  >
                    <i className="bi bi-folder2" aria-hidden="true"></i>
                    {col.name}
                    <span className="memo-collection-chip__count">{col.memo_count}</span>
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
                <button type="button" className="memo-bulk-btn" onClick={() => void executeBulkAction("pin")} disabled={!hasSelection || bulkLoading} data-tooltip="ピン留め" data-tooltip-placement="top">
                  <i className="bi bi-pin-angle"></i>ピン留め
                </button>
                <button type="button" className="memo-bulk-btn" onClick={() => void executeBulkAction("unpin")} disabled={!hasSelection || bulkLoading} data-tooltip="ピン留め解除" data-tooltip-placement="top">
                  <i className="bi bi-pin-angle-fill"></i>解除
                </button>
                <button type="button" className="memo-bulk-btn" onClick={() => void executeBulkAction("archive")} disabled={!hasSelection || bulkLoading} data-tooltip="アーカイブ" data-tooltip-placement="top">
                  <i className="bi bi-archive"></i>アーカイブ
                </button>
                <button type="button" className="memo-bulk-btn" onClick={() => void executeBulkAction("unarchive")} disabled={!hasSelection || bulkLoading} data-tooltip="アーカイブ解除" data-tooltip-placement="top">
                  <i className="bi bi-archive-fill"></i>解除
                </button>
                {collections.length > 0 && (
                  <div className="memo-bulk-bar__tag-group">
                    <MemoSelect
                      className="memo-select--sm"
                      value={String(bulkCollectionId ?? "")}
                      onChange={(v) => setBulkCollectionId(v === "" ? null : Number(v))}
                      options={[
                        { value: "", label: "コレクション選択" },
                        ...collections.map((c) => ({ value: String(c.id), label: c.name })),
                      ]}
                    />
                    <button type="button" className="memo-bulk-btn" onClick={() => void executeBulkAction("set_collection", { collectionId: bulkCollectionId })} disabled={!hasSelection || bulkLoading || bulkCollectionId === null} data-tooltip="コレクション設定" data-tooltip-placement="top">
                      <i className="bi bi-folder2"></i>設定
                    </button>
                    <button type="button" className="memo-bulk-btn" onClick={() => void executeBulkAction("clear_collection")} disabled={!hasSelection || bulkLoading} data-tooltip="コレクション解除" data-tooltip-placement="top">
                      解除
                    </button>
                  </div>
                )}
                <button type="button" className="memo-bulk-btn memo-bulk-btn--danger" onClick={() => void executeBulkAction("delete")} disabled={!hasSelection || bulkLoading} data-tooltip="削除" data-tooltip-placement="top">
                  <i className="bi bi-trash3"></i>削除
                </button>
              </div>
            </div>
          )}

          {/* ── Quick capture ── */}
          <section className={`memo-card memo-compose-panel memo-quick-capture${composeIsExpanded ? " is-expanded" : ""}`}>
            {!composeIsExpanded ? (
              <button
                type="button"
                className="memo-quick-capture__collapsed"
                onClick={() => setIsComposeExpanded(true)}
                aria-label="新しいメモを作成"
              >
                <span>メモを入力...</span>
                <span className="memo-quick-capture__shortcuts" aria-hidden="true">
                  <i className="bi bi-check2-square"></i>
                  <i className="bi bi-image"></i>
                  <i className="bi bi-palette"></i>
                </span>
              </button>
            ) : (
              <form method="post" className="memo-form memo-form--quick" onSubmit={handleSubmitMemo}>
                <div className="form-group">
                  <label htmlFor="title" className="sr-only">タイトル</label>
                  <input
                    id="title"
                    name="title"
                    data-agent-id="memo.title"
                    type="text"
                    className="memo-control memo-quick-capture__title-input"
                    value={formState.title}
                    onChange={handleFormChange}
                    maxLength={255}
                    placeholder="タイトル"
                    autoFocus={!hasComposeDraft}
                  />
                </div>

                <div className="form-group">
                  <div className="memo-response-header memo-quick-capture__response-header">
                    <label htmlFor="ai_response" className="sr-only">本文</label>
                    <div className="memo-response-tabs">
                      <button type="button" className={`memo-response-tab${!previewMode ? " is-active" : ""}`} onClick={() => setPreviewMode(false)}>
                        <i className="bi bi-pencil" aria-hidden="true"></i>編集
                      </button>
                      <button type="button" className={`memo-response-tab${previewMode ? " is-active" : ""}`} onClick={() => setPreviewMode(true)} disabled={!formState.ai_response.trim()}>
                        <i className="bi bi-eye" aria-hidden="true"></i>プレビュー
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
                      data-agent-id="memo.ai-response"
                      className="memo-control memo-control--response"
                      value={formState.ai_response}
                      onChange={handleFormChange}
                      placeholder="メモを入力..."
                      required
                    />
                  )}
                </div>

                <div className="memo-quick-capture__bottom-row">
                  {collections.length > 0 && (
                    <MemoSelect
                      id="compose_collection"
                      className="memo-select--quick"
                      value={String(formState.collection_id ?? "")}
                      onChange={(v) => setFormState((prev) => ({ ...prev, collection_id: v === "" ? null : Number(v) }))}
                      options={[
                        { value: "", label: "コレクションなし" },
                        ...collections.map((c) => ({ value: String(c.id), label: c.name })),
                      ]}
                    />
                  )}
                  <button
                    type="button"
                    className={`memo-ai-suggest-btn${aiSuggesting ? " is-loading" : ""}`}
                    onClick={() => { void handleAiSuggest(); }}
                    disabled={aiSuggesting || !formState.ai_response.trim()}
                    data-tooltip="AIがタイトルを提案"
                    data-tooltip-placement="top"
                  >
                    {aiSuggesting
                      ? <><i className="bi bi-arrow-repeat memo-spin" aria-hidden="true"></i>提案中...</>
                      : <><i className="bi bi-stars" aria-hidden="true"></i>AIタイトル</>}
                  </button>
                  <div className="memo-quick-capture__actions">
                    <button
                      type="button"
                      className="secondary-button"
                      onClick={() => {
                        setFormState({ ai_response: "", title: "", collection_id: null });
                        setPreviewMode(false);
                        setIsComposeExpanded(false);
                      }}
                      disabled={submitting}
                    >
                      閉じる
                    </button>
                    <button type="submit" className="primary-button" data-agent-id="memo.save" disabled={submitting}>
                      <i className="bi bi-check2" aria-hidden="true"></i>
                      完了
                    </button>
                  </div>
                </div>
              </form>
            )}
          </section>

          <div className={`memo-board memo-board--${viewMode}`}>
            {/* ── Memo list ── */}
            <section className="memo-history-panel">
              <div className="memo-panel__header">
                <div className="memo-panel__heading">
                  <h2><i className="bi bi-list-ul" aria-hidden="true"></i>メモ一覧</h2>
                  {activeCollection && <CollectionBadge name={activeCollection.name} color={activeCollection.color || "#6b7280"} />}
                </div>
                <span className="memo-panel__count">
                  <i className="bi bi-journal-text" aria-hidden="true"></i>
                  {totalMemoCount}件
                </span>
              </div>

              {memoLoadError && <div className="memo-history__empty">{memoLoadError.message}</div>}
              {!memoLoadError && memoListLoading && memos.length === 0 && (
                <div className="memo-history__empty"><InlineLoading label="メモを読み込んでいます..." className="mx-auto" /></div>
              )}
              {!memoLoadError && !memoListLoading && memos.length === 0 && (
                <div className="memo-history__empty">条件に一致するメモがありません。</div>
              )}

              {memos.length > 0 && (() => {
                const renderMemoCard = (memo: MemoSummary) => {
                  const memoId = String(memo.id);
                  const isMenuOpen = openMenuMemoId === memoId;
                  const isBusy = actionLoadingId === memoId;
                  const isSelected = selectedIds.has(memoId);
                  const isCopied = copiedMemoId === memoId;
                  const canDragMemo = canDragMemos && !isBusy;
                  const displayDate = formatDateTime(memo.updated_at || memo.created_at) || memo.updated_at || memo.created_at || "";
                  const accent = memo.collection_color || "";
                  const cardStyle = accent ? ({ "--memo-card-accent": accent } as React.CSSProperties) : undefined;

                  return (
                    <li key={memoId}>
                      <article
                        ref={(el) => {
                          if (el) cardRefs.current.set(memoId, el);
                          else cardRefs.current.delete(memoId);
                        }}
                        className={`memo-item${memo.is_archived ? " is-archived" : ""}${memo.is_pinned ? " is-pinned" : ""}${isSelected ? " is-selected" : ""}${accent ? " has-accent" : ""}${canDragMemo ? " is-reorderable" : ""}${draggedMemoId === memoId ? " is-dragging" : ""}`}
                        style={cardStyle}
                        draggable={canDragMemo}
                        onDragStart={(event) => handleMemoDragStart(event, memo)}
                        onDragEnd={clearMemoDragState}
                        aria-grabbed={draggedMemoId === memoId}
                      >
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

                        {!isBulkMode && (
                          <button
                            type="button"
                            className={`memo-item__pin${memo.is_pinned ? " is-pinned" : ""}`}
                            onClick={() => { void handleTogglePin(memo); }}
                            disabled={isBusy}
                            aria-label={memo.is_pinned ? "ピン留めを解除" : "ピン留め"}
                            aria-pressed={memo.is_pinned}
                            data-tooltip={memo.is_pinned ? "ピン留めを解除" : "ピン留め"}
                            data-tooltip-placement="left"
                          >
                            <i className={`bi ${memo.is_pinned ? "bi-pin-angle-fill" : "bi-pin-angle"}`} aria-hidden="true"></i>
                          </button>
                        )}

                        <button
                          type="button"
                          className="memo-item__open memo-item__open--content"
                          onClick={() => { if (isBulkMode) { toggleSelectMemo(memoId); return; } void openMemoDetail(memoId); }}
                        >
                          <h3 className="memo-item__title">{memo.title || "保存したメモ"}</h3>
                          {memo.excerpt && <MemoMarkdown text={parseMemoText(memo.excerpt)} className="memo-item__excerpt" />}
                        </button>

                        <footer className="memo-item__footer">
                          <div className="memo-item__meta">
                            {memo.collection_name && (
                              <CollectionBadge name={memo.collection_name} color={memo.collection_color || "#6b7280"} />
                            )}
                            {displayDate && (
                              <time className="memo-item__date">
                                <i className="bi bi-clock" aria-hidden="true"></i>
                                {displayDate}
                              </time>
                            )}
                            {memo.is_archived && (
                              <span className="memo-item__archive-badge" aria-label="アーカイブ済み" data-tooltip="アーカイブ済み" data-tooltip-placement="top">
                                <i className="bi bi-archive-fill" aria-hidden="true"></i>
                              </span>
                            )}
                            {memo.is_active && (
                              <span className="memo-item__status-icon" aria-label="共有中" data-tooltip="共有中" data-tooltip-placement="top">
                                <i className="bi bi-link-45deg" aria-hidden="true"></i>
                              </span>
                            )}
                          </div>

                          {!isBulkMode && (
                            <div className="memo-item__actions">
                              <button
                                type="button"
                                className={`memo-item__action${isCopied ? " is-copied" : ""}`}
                                onClick={() => { void copyMemoExcerpt(memo); }}
                                disabled={isBusy}
                                aria-label={isCopied ? "コピーしました" : "要約をコピー"}
                                data-tooltip={isCopied ? "コピーしました" : "要約をコピー"}
                                data-tooltip-placement="top"
                              >
                                <i className={`bi ${isCopied ? "bi-check2" : "bi-files"}`}></i>
                              </button>
                              <button
                                type="button"
                                className="memo-item__action"
                                onClick={(event) => { event.stopPropagation(); void handleToggleArchive(memo); }}
                                disabled={isBusy}
                                aria-label={memo.is_archived ? "アーカイブを解除" : "アーカイブ"}
                                data-tooltip={memo.is_archived ? "アーカイブを解除" : "アーカイブ"}
                                data-tooltip-placement="top"
                              >
                                <i className={`bi ${memo.is_archived ? "bi-archive-fill" : "bi-archive"}`}></i>
                              </button>
                              <div className="memo-item__menu-wrap">
                                <button
                                  type="button"
                                  className={`memo-item__action${isMenuOpen ? " is-active" : ""}`}
                                  onClick={(event) => { toggleMemoActionMenu(memoId, event.currentTarget); }}
                                  disabled={isBusy}
                                  data-tooltip="その他の操作"
                                  data-tooltip-placement="top"
                                  aria-haspopup="true"
                                  aria-expanded={isMenuOpen}
                                  aria-label="その他の操作"
                                >
                                  <i className="bi bi-three-dots"></i>
                                </button>
                                {isMenuOpen && menuPosition && createPortal(
                                  <div
                                    className="memo-item__dropdown"
                                    role="menu"
                                    style={{
                                      position: "fixed",
                                      top: menuPosition.top,
                                      left: menuPosition.left,
                                      width: menuPosition.width,
                                      maxHeight: menuPosition.maxHeight,
                                    }}
                                  >
                                    <button
                                      type="button"
                                      className="memo-item__dropdown-item"
                                      role="menuitem"
                                      onClick={() => { void openShareModal(memo); setOpenMenuMemoId(""); setMenuPosition(null); }}
                                    >
                                      <i className="bi bi-share"></i>
                                      共有設定
                                    </button>
                                    <button
                                      type="button"
                                      className="memo-item__dropdown-item memo-item__dropdown-item--danger"
                                      role="menuitem"
                                      onClick={() => { void handleDeleteMemo(memo); setOpenMenuMemoId(""); setMenuPosition(null); }}
                                    >
                                      <i className="bi bi-trash3"></i>
                                      削除
                                    </button>
                                  </div>,
                                  document.body,
                                )}
                              </div>
                            </div>
                          )}
                        </footer>
                      </article>
                    </li>
                  );
                };

                const showSectionLabels = pinnedMemos.length > 0 && otherMemos.length > 0;

                return (
                  <div className="memo-history__sections">
                    {pinnedMemos.length > 0 && (
                      <section className="memo-history__section">
                        {showSectionLabels && (
                          <h3 className="memo-history__section-label">
                            <i className="bi bi-pin-angle-fill" aria-hidden="true"></i>ピン留め
                          </h3>
                        )}
                        <ul
                          className={`memo-history__list${draggedMemoId && canReorderCurrentView ? " is-drop-ready" : ""}`}
                          onDragOver={(event) => handleMemoSectionDragOver(event, pinnedMemos)}
                          onDrop={(event) => { void handleMemoDrop(event); }}
                        >
                          {pinnedMemos.map(renderMemoCard)}
                        </ul>
                      </section>
                    )}
                    {otherMemos.length > 0 && (
                      <section className="memo-history__section">
                        {showSectionLabels && (
                          <h3 className="memo-history__section-label">その他</h3>
                        )}
                        <ul
                          className={`memo-history__list${draggedMemoId && canReorderCurrentView ? " is-drop-ready" : ""}`}
                          onDragOver={(event) => handleMemoSectionDragOver(event, otherMemos)}
                          onDrop={(event) => { void handleMemoDrop(event); }}
                        >
                          {otherMemos.map(renderMemoCard)}
                        </ul>
                      </section>
                    )}
                  </div>
                );
              })()}
            </section>

          </div>
        </div>

        {/* ── Memo detail modal ── */}
        <div className={`memo-modal${selectedMemo ? " is-visible" : ""}`} aria-hidden={selectedMemo ? "false" : "true"}>
          <div className="memo-modal__overlay" onClick={() => { void closeMemoDetail(); }}></div>
          <div className="memo-modal__content" role="dialog" aria-modal="true" aria-labelledby="memoModalTitle">
            <button type="button" className="memo-modal__close" aria-label="閉じる" onClick={() => { void closeMemoDetail(); }}>
              <i className="bi bi-x-lg"></i>
            </button>
            <header className="memo-modal__header">
              <div className="memo-modal__title-row">
                <div>
                  <h3 id="memoModalTitle">{detailEditTitle || selectedMemo?.title || "保存したメモ"}</h3>
                  <p className="memo-modal__date">{formatDateTime(selectedMemo?.updated_at || selectedMemo?.created_at) || selectedMemo?.created_at || ""}</p>
                </div>
                {selectedMemo && (
                  <div className="memo-modal__header-actions">
                    <button
                      type="button"
                      className={`memo-modal__icon-btn${detailMetaOpen ? " is-active" : ""}`}
                      onClick={() => setDetailMetaOpen((value) => !value)}
                      aria-label="タイトル・コレクションを編集"
                      aria-expanded={detailMetaOpen}
                      aria-controls="memo-detail-meta-panel"
                      data-tooltip="タイトル・コレクション"
                      data-tooltip-placement="bottom"
                    >
                      <i className="bi bi-sliders" aria-hidden="true"></i>
                    </button>
                    <div className={`memo-modal__autosave-status memo-modal__autosave-status--${detailSaveStatus}`} role="status" aria-live="polite">
                      {detailSaveStatus === "saving" && <><i className="bi bi-arrow-repeat memo-spin" aria-hidden="true"></i>保存中...</>}
                      {detailSaveStatus === "saved" && <><i className="bi bi-check2" aria-hidden="true"></i>保存済み</>}
                      {detailSaveStatus === "idle" && detailHasUnsavedChanges && <><i className="bi bi-clock" aria-hidden="true"></i>自動保存待ち</>}
                      {detailSaveStatus === "idle" && !detailHasUnsavedChanges && <><i className="bi bi-check2" aria-hidden="true"></i>保存済み</>}
                      {detailSaveStatus === "error" && <><i className="bi bi-exclamation-triangle" aria-hidden="true"></i>{detailSaveError || "自動保存に失敗しました"}</>}
                    </div>
                  </div>
                )}
              </div>
            </header>
            {detailLoading && <div className="memo-history__empty"><InlineLoading label="メモを読み込んでいます..." className="mx-auto" /></div>}
            {!detailLoading && detailError && <div className="memo-history__empty">{detailError}</div>}
            {!detailLoading && selectedMemo && (
              <div className="memo-modal__body memo-modal__body--edit">
                <section className="memo-modal__section memo-modal__section--full memo-modal__edit-form">
                  <div className="memo-modal__edit-fields">
                    {detailMetaOpen && (
                      <div id="memo-detail-meta-panel" className="memo-modal__meta-panel">
                        <div className="memo-modal__edit-field">
                          <label htmlFor="memo-detail-title">タイトル</label>
                          <input
                            id="memo-detail-title"
                            type="text"
                            className="memo-control"
                            value={detailEditTitle}
                            onChange={(event) => setDetailEditTitle(event.target.value)}
                            placeholder="空欄なら回答1行目を採用"
                            maxLength={255}
                          />
                        </div>
                        {collections.length > 0 && (
                          <div className="memo-modal__edit-field">
                            <label htmlFor="memo-detail-collection">コレクション</label>
                            <MemoSelect
                              id="memo-detail-collection"
                              className="memo-select--full"
                              value={String(detailEditCollectionId ?? "")}
                              onChange={(value) => setDetailEditCollectionId(value === "" ? null : Number(value))}
                              options={[
                                { value: "", label: "コレクションなし" },
                                ...collections.map((collection) => ({ value: String(collection.id), label: collection.name })),
                              ]}
                            />
                          </div>
                        )}
                      </div>
                    )}
                    <div className="memo-modal__response-header">
                      <label htmlFor="memo-detail-ai-response">AIの回答</label>
                      <div className="memo-response-tabs">
                        <button
                          type="button"
                          className={`memo-response-tab${!detailPreviewMode ? " is-active" : ""}`}
                          onClick={() => setDetailPreviewMode(false)}
                        >
                          <i className="bi bi-code-slash" aria-hidden="true"></i>編集
                        </button>
                        <button
                          type="button"
                          className={`memo-response-tab${detailPreviewMode ? " is-active" : ""}`}
                          onClick={() => setDetailPreviewMode(true)}
                          disabled={!detailEditAiResponse.trim()}
                        >
                          <i className="bi bi-eye" aria-hidden="true"></i>プレビュー
                        </button>
                      </div>
                    </div>
                    {detailPreviewMode ? (
                      <div className="memo-preview-pane memo-modal__preview-pane">
                        {detailEditAiResponse.trim()
                          ? <MemoMarkdown text={parseMemoText(detailEditAiResponse)} className="memo-preview-content" />
                          : <p className="memo-preview-empty">プレビューするテキストがありません。</p>}
                      </div>
                    ) : (
                      <textarea
                        id="memo-detail-ai-response"
                        className="memo-control memo-modal__edit-textarea memo-modal__edit-textarea--response"
                        value={detailEditAiResponse}
                        onChange={(event) => setDetailEditAiResponse(event.target.value)}
                        placeholder="AIからの回答"
                        required
                      />
                    )}
                  </div>
                </section>
              </div>
            )}
          </div>
        </div>

        {/* ── Share modal ── */}
        <div
          id="memo-share-modal"
          className={`memo-share-modal cc-share-modal${isShareModalOpen ? " is-visible" : ""}`}
          role="dialog"
          aria-modal="true"
          aria-hidden={isShareModalOpen ? "false" : "true"}
          aria-labelledby="memoShareTitle"
          onClick={(event) => {
            if (event.target === event.currentTarget) {
              closeShareModal();
            }
          }}
        >
          <div className="memo-share-modal__content cc-share-modal__content" tabIndex={-1}>
            <button type="button" className="memo-share-modal__close cc-share-modal__close" aria-label="共有モーダルを閉じる" onClick={closeShareModal}>
              <i className="bi bi-x-lg"></i>
            </button>
            <header className="memo-share-modal__header cc-share-modal__header">
              <h3 id="memoShareTitle">メモを共有</h3>
              <p className="cc-share-modal__lead">
                このメモ専用のURLをコピーしたり、そのまま共有できます。
              </p>
            </header>
            <div className="memo-share-modal__body cc-share-modal__body">
              <div className="memo-share-modal__row cc-share-modal__row">
                <input
                  id="memo-share-link-input"
                  type="text"
                  readOnly
                  value={shareUrl}
                  placeholder="共有リンクを準備しています"
                />
              </div>
              {shareStatus && <p className={`memo-share-modal__status cc-share-modal__status memo-share-modal__status--${shareStatus.type}${shareStatus.type === "error" ? " cc-share-modal__status--error" : ""}`}>{shareStatus.text}</p>}
              <div className="memo-share-modal__actions cc-share-modal__actions">
                <button type="button" className="primary-button memo-share-modal__icon-btn cc-share-modal__icon-btn" aria-label="リンクをコピー" title="リンクをコピー" onClick={() => { void copyShareLink(); }} disabled={shareLoading || !shareUrl}><i className="bi bi-files"></i></button>
                {supportsNativeShare && (
                  <button type="button" className="primary-button memo-share-modal__icon-btn cc-share-modal__icon-btn" aria-label="端末で共有" title="端末で共有" onClick={() => { void openNativeShareSheet(); }} disabled={shareLoading || !shareUrl}><i className="bi bi-box-arrow-up-right"></i></button>
                )}
              </div>
              <div className="memo-share-modal__sns cc-share-modal__sns">
                <a target="_blank" rel="noopener noreferrer" href={shareSnsLinks.x}>
                  <svg className="share-x-icon" viewBox="0 0 24 24" aria-hidden="true">
                    <path
                      fill="currentColor"
                      d="M18.901 1.153h3.68l-8.04 9.188L24 22.847h-7.406l-5.8-7.584-6.63 7.584H.48l8.6-9.83L0 1.154h7.594l5.243 6.932L18.901 1.153Zm-1.291 19.49h2.039L6.486 3.24H4.298L17.61 20.643Z"
                    ></path>
                  </svg>
                  <span>X</span>
                </a>
                <a target="_blank" rel="noopener noreferrer" href={shareSnsLinks.line}>
                  <i className="bi bi-chat-dots"></i>
                  <span>LINE</span>
                </a>
                <a target="_blank" rel="noopener noreferrer" href={shareSnsLinks.facebook}>
                  <i className="bi bi-facebook"></i>
                  <span>Facebook</span>
                </a>
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
                        data-tooltip={c}
                        data-tooltip-placement="top"
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
                              <button type="button" key={c} className={`memo-collection-preset${editingCollectionColor === c ? " is-active" : ""}`} style={{ background: c }} onClick={() => setEditingCollectionColor(c)} data-tooltip={c} data-tooltip-placement="top" />
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
                        <button type="button" className="memo-collection-item__action" onClick={() => { setEditingCollectionId(col.id); setEditingCollectionName(col.name); setEditingCollectionColor(col.color); }} data-tooltip="編集" data-tooltip-placement="top">
                          <i className="bi bi-pencil"></i>
                        </button>
                        <button type="button" className="memo-collection-item__action memo-collection-item__action--danger" onClick={() => { void handleDeleteCollection(col.id, col.name); }} disabled={collectionActionLoading} data-tooltip="削除" data-tooltip-placement="top">
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
