import { SeoHead } from "../components/SeoHead";
import { useRouter } from "next/router";
import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent, type FormEvent } from "react";
import useSWR from "swr";

import "../scripts/core/csrf";
import { InlineLoading } from "../components/ui/inline_loading";
import { formatDateTime } from "../lib/datetime";
import { formatLLMOutput } from "../scripts/chat/chat_ui";
import { copyTextToClipboard, renderSanitizedHTML } from "../scripts/chat/message_utils";
import { setLoggedInState } from "../scripts/core/app_state";
import { fetchJsonOrThrow } from "../scripts/core/runtime_validation";

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
};

type MemoDetail = MemoSummary & {
  input_content?: string;
  ai_response?: string;
};

type MemoListPayload = {
  memos?: MemoSummary[];
  total?: number;
  error?: string;
};

type MemoListState = {
  memos: MemoSummary[];
  total: number;
};

type MemoDetailPayload = {
  memo?: MemoDetail;
  error?: string;
};

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

type FlashState = {
  type: "success" | "error";
  text: string;
};

type HttpError = Error & { status?: number };

const DEFAULT_LIMIT = 50;
const MEMO_SHARE_TITLE = "Chat Core 共有メモ";
const MEMO_SHARE_TEXT = "このメモを共有しました。";
const SHARE_EXPIRES_OPTIONS = [
  { value: "7", label: "7日で期限切れ" },
  { value: "30", label: "30日で期限切れ" },
  { value: "90", label: "90日で期限切れ" },
  { value: "never", label: "無期限" },
] as const;

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
  return raw
    .split(/[,\s、，]+/)
    .map((tag) => tag.trim())
    .filter(Boolean);
}

function buildMemoListUrl(options: {
  query: string;
  tag: string;
  dateFrom: string;
  dateTo: string;
  sort: string;
  archiveScope: string;
}) {
  const params = new URLSearchParams();
  params.set("limit", String(DEFAULT_LIMIT));
  params.set("offset", "0");
  params.set("sort", options.sort);
  params.set("pinned_first", "1");

  const trimmedQuery = options.query.trim();
  const trimmedTag = options.tag.trim();
  if (trimmedQuery) {
    params.set("q", trimmedQuery);
  }
  if (trimmedTag) {
    params.set("tag", trimmedTag);
  }
  if (options.dateFrom) {
    params.set("date_from", options.dateFrom);
  }
  if (options.dateTo) {
    params.set("date_to", options.dateTo);
  }

  if (options.archiveScope === "all") {
    params.set("include_archived", "1");
  } else if (options.archiveScope === "archived") {
    params.set("only_archived", "1");
  }

  return `/memo/api/recent?${params.toString()}`;
}

const loadMemoList = async (url: string): Promise<MemoListState> => {
  const res = await fetch(url, { credentials: "same-origin" });
  const data: MemoListPayload = await res.json().catch(() => ({}));
  if (res.status === 401) {
    return { memos: [], total: 0 };
  }
  if (!res.ok) {
    const error = new Error(data.error || `メモの取得に失敗しました (${res.status})`) as HttpError;
    error.status = res.status;
    throw error;
  }
  return {
    memos: Array.isArray(data.memos) ? data.memos : [],
    total: typeof data.total === "number" ? data.total : 0,
  };
};

async function loadMemoDetail(memoId: string | number) {
  const { payload } = await fetchJsonOrThrow<MemoDetailPayload>(
    `/memo/api/${memoId}`,
    { credentials: "same-origin" },
    {
      defaultMessage: "メモの詳細取得に失敗しました。",
      hasApplicationError: (data) => !data.memo,
    },
  );
  return payload.memo || null;
}

function MemoMarkdown({ text, className }: { text: string; className?: string }) {
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    renderSanitizedHTML(containerRef.current, formatLLMOutput(text || ""));
  }, [text]);

  return <div ref={containerRef} className={className}></div>;
}

export default function MemoPage() {
  const router = useRouter();

  const [formState, setFormState] = useState({
    input_content: "",
    ai_response: "",
    title: "",
    tags: "",
  });
  const [flashState, setFlashState] = useState<FlashState | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [isLoggedIn, setIsLoggedIn] = useState(false);

  const [query, setQuery] = useState("");
  const [tagFilter, setTagFilter] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [sortMode, setSortMode] = useState("recent");
  const [archiveScope, setArchiveScope] = useState("active");

  const [activeMobileTab, setActiveMobileTab] = useState<"list" | "compose">("list");

  const [selectedMemo, setSelectedMemo] = useState<MemoDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");

  const [editingMemoId, setEditingMemoId] = useState<string>("");
  const [quickEditTitle, setQuickEditTitle] = useState("");
  const [quickEditTags, setQuickEditTags] = useState("");
  const [actionLoadingId, setActionLoadingId] = useState<string>("");

  const [isShareModalOpen, setIsShareModalOpen] = useState(false);
  const [shareMemoId, setShareMemoId] = useState<string>("");
  const [shareMemoTitle, setShareMemoTitle] = useState("");
  const [shareState, setShareState] = useState<SharePayload | null>(null);
  const [shareStatus, setShareStatus] = useState<FlashState | null>(null);
  const [shareLoading, setShareLoading] = useState(false);
  const [shareExpiry, setShareExpiry] = useState<(typeof SHARE_EXPIRES_OPTIONS)[number]["value"]>("30");
  const [supportsNativeShare, setSupportsNativeShare] = useState(false);

  const listUrl = useMemo(
    () => buildMemoListUrl({ query, tag: tagFilter, dateFrom, dateTo, sort: sortMode, archiveScope }),
    [archiveScope, dateFrom, dateTo, query, sortMode, tagFilter],
  );

  const {
    data: memoList = { memos: [], total: 0 },
    error: memoLoadError,
    isLoading: memoListLoading,
    mutate,
  } = useSWR<MemoListState>(listUrl, loadMemoList, {
    revalidateOnFocus: true,
    keepPreviousData: true,
    dedupingInterval: 3000,
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
    if (!shareUrl) {
      return { x: "#", line: "#", facebook: "#" };
    }
    const encodedUrl = encodeURIComponent(shareUrl);
    const encodedText = encodeURIComponent(MEMO_SHARE_TEXT);
    return {
      x: `https://twitter.com/intent/tweet?url=${encodedUrl}&text=${encodedText}`,
      line: `https://social-plugins.line.me/lineit/share?url=${encodedUrl}`,
      facebook: `https://www.facebook.com/sharer/sharer.php?u=${encodedUrl}`,
    };
  }, [shareUrl]);

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
    const open = Boolean(selectedMemo) || isShareModalOpen;
    document.body.classList.toggle("modal-open", open);
    return () => {
      document.body.classList.remove("modal-open");
    };
  }, [isShareModalOpen, selectedMemo]);

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
    if (router.query.saved === "1") {
      setFlashState({ type: "success", text: "メモを保存しました。" });
    }
  }, [router.isReady, router.query.saved]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (isShareModalOpen) {
        setIsShareModalOpen(false);
        return;
      }
      if (selectedMemo) {
        setSelectedMemo(null);
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [isShareModalOpen, selectedMemo]);

  const showFlash = useCallback((type: "success" | "error", text: string) => {
    setFlashState({ type, text });
  }, []);

  const handleFormChange = useCallback((event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const { name, value } = event.target;
    setFormState((prev) => ({ ...prev, [name]: value }));
  }, []);

  const handleSubmitMemo = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      setFlashState(null);

      if (!formState.ai_response.trim()) {
        showFlash("error", "AIの回答を入力してください。");
        return;
      }

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

        setFormState({
          input_content: "",
          ai_response: "",
          title: "",
          tags: "",
        });
        showFlash("success", "メモを保存しました。");
        setActiveMobileTab("list");
        void router.replace("/memo?saved=1", undefined, { shallow: true });
        void mutate();
      } catch (error) {
        showFlash("error", error instanceof Error ? error.message : "メモの保存に失敗しました。");
      } finally {
        setSubmitting(false);
      }
    },
    [formState, mutate, router, showFlash],
  );

  const openMemoDetail = useCallback(async (memoId: string | number) => {
    setDetailError("");
    setDetailLoading(true);
    try {
      const memo = await loadMemoDetail(memoId);
      if (!memo) {
        setDetailError("メモの詳細を取得できませんでした。");
        return;
      }
      setSelectedMemo(memo);
    } catch (error) {
      setDetailError(error instanceof Error ? error.message : "メモの詳細取得に失敗しました。");
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const refreshSelectedMemoIfNeeded = useCallback(async () => {
    if (!selectedMemo?.id) return;
    try {
      const refreshed = await loadMemoDetail(selectedMemo.id);
      if (refreshed) {
        setSelectedMemo(refreshed);
      }
    } catch {
      return;
    }
  }, [selectedMemo?.id]);

  const withActionLoading = useCallback(
    async (memoId: string | number, action: () => Promise<void>) => {
      const id = String(memoId);
      setActionLoadingId(id);
      try {
        await action();
      } finally {
        setActionLoadingId("");
      }
    },
    [],
  );

  const handleTogglePin = useCallback(
    async (memo: MemoSummary) => {
      await withActionLoading(memo.id, async () => {
        try {
          await fetchJsonOrThrow(
            `/memo/api/${memo.id}/pin`,
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              credentials: "same-origin",
              body: JSON.stringify({ enabled: !memo.is_pinned }),
            },
            { defaultMessage: "ピン留め更新に失敗しました。" },
          );
          showFlash("success", memo.is_pinned ? "ピン留めを解除しました。" : "ピン留めしました。");
          await mutate();
          await refreshSelectedMemoIfNeeded();
        } catch (error) {
          showFlash("error", error instanceof Error ? error.message : "ピン留め更新に失敗しました。");
        }
      });
    },
    [mutate, refreshSelectedMemoIfNeeded, showFlash, withActionLoading],
  );

  const handleToggleArchive = useCallback(
    async (memo: MemoSummary) => {
      await withActionLoading(memo.id, async () => {
        try {
          await fetchJsonOrThrow(
            `/memo/api/${memo.id}/archive`,
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              credentials: "same-origin",
              body: JSON.stringify({ enabled: !memo.is_archived }),
            },
            { defaultMessage: "アーカイブ更新に失敗しました。" },
          );
          showFlash("success", memo.is_archived ? "アーカイブを解除しました。" : "アーカイブしました。");
          await mutate();
          await refreshSelectedMemoIfNeeded();
        } catch (error) {
          showFlash("error", error instanceof Error ? error.message : "アーカイブ更新に失敗しました。");
        }
      });
    },
    [mutate, refreshSelectedMemoIfNeeded, showFlash, withActionLoading],
  );

  const handleDeleteMemo = useCallback(
    async (memo: MemoSummary) => {
      const confirmed = window.confirm(`「${memo.title || "保存したメモ"}」を削除しますか？`);
      if (!confirmed) return;
      await withActionLoading(memo.id, async () => {
        try {
          await fetchJsonOrThrow(
            `/memo/api/${memo.id}`,
            {
              method: "DELETE",
              credentials: "same-origin",
            },
            { defaultMessage: "メモの削除に失敗しました。" },
          );
          showFlash("success", "メモを削除しました。");
          if (selectedMemo?.id && String(selectedMemo.id) === String(memo.id)) {
            setSelectedMemo(null);
          }
          await mutate();
        } catch (error) {
          showFlash("error", error instanceof Error ? error.message : "メモの削除に失敗しました。");
        }
      });
    },
    [mutate, selectedMemo?.id, showFlash, withActionLoading],
  );

  const startQuickEdit = useCallback((memo: MemoSummary) => {
    setEditingMemoId(String(memo.id));
    setQuickEditTitle(memo.title || "");
    setQuickEditTags(memo.tags || "");
  }, []);

  const cancelQuickEdit = useCallback(() => {
    setEditingMemoId("");
    setQuickEditTitle("");
    setQuickEditTags("");
  }, []);

  const saveQuickEdit = useCallback(
    async (memoId: string | number) => {
      await withActionLoading(memoId, async () => {
        try {
          await fetchJsonOrThrow(
            `/memo/api/${memoId}`,
            {
              method: "PATCH",
              headers: { "Content-Type": "application/json" },
              credentials: "same-origin",
              body: JSON.stringify({
                title: quickEditTitle,
                tags: quickEditTags,
              }),
            },
            { defaultMessage: "メモ更新に失敗しました。" },
          );
          cancelQuickEdit();
          showFlash("success", "メモを更新しました。");
          await mutate();
          await refreshSelectedMemoIfNeeded();
        } catch (error) {
          showFlash("error", error instanceof Error ? error.message : "メモ更新に失敗しました。");
        }
      });
    },
    [
      cancelQuickEdit,
      mutate,
      quickEditTags,
      quickEditTitle,
      refreshSelectedMemoIfNeeded,
      showFlash,
      withActionLoading,
    ],
  );

  const copyMemoExcerpt = useCallback(async (memo: MemoSummary) => {
    const content = `${memo.title || "保存したメモ"}\n\n${parseMemoText(memo.excerpt)}`;
    try {
      await copyTextToClipboard(content.trim());
      showFlash("success", "メモの要約をコピーしました。");
    } catch (error) {
      showFlash("error", error instanceof Error ? error.message : "コピーに失敗しました。");
    }
  }, [showFlash]);

  const loadShareState = useCallback(async (memoId: string | number) => {
    const { payload } = await fetchJsonOrThrow<SharePayload>(
      `/memo/api/${memoId}/share`,
      { credentials: "same-origin" },
      { defaultMessage: "共有情報の取得に失敗しました。" },
    );
    setShareState(payload);
    if (payload.expires_at) {
      const expiresAt = new Date(payload.expires_at);
      const diffDays = Math.round((expiresAt.getTime() - Date.now()) / (24 * 60 * 60 * 1000));
      if (diffDays <= 8 && diffDays > 0) {
        setShareExpiry("7");
      } else if (diffDays <= 32 && diffDays > 0) {
        setShareExpiry("30");
      } else if (diffDays <= 95 && diffDays > 0) {
        setShareExpiry("90");
      } else {
        setShareExpiry("30");
      }
    } else {
      setShareExpiry("never");
    }
  }, []);

  const openShareModal = useCallback(
    async (memo: MemoSummary) => {
      const memoId = String(memo.id || "");
      if (!memoId) {
        showFlash("error", "共有対象のメモが見つかりません。");
        return;
      }
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
        setShareStatus({
          type: "error",
          text: error instanceof Error ? error.message : "共有情報の取得に失敗しました。",
        });
      } finally {
        setShareLoading(false);
      }
    },
    [loadShareState, showFlash],
  );

  const closeShareModal = useCallback(() => {
    setIsShareModalOpen(false);
    setShareMemoId("");
    setShareMemoTitle("");
    setShareStatus(null);
    setShareState(null);
  }, []);

  const createShareLink = useCallback(
    async (forceRefresh: boolean) => {
      if (!shareMemoId) return;
      setShareLoading(true);
      setShareStatus({ type: "success", text: forceRefresh ? "共有リンクを再生成しています..." : "共有リンクを作成しています..." });
      const expiresInDays = shareExpiry === "never" ? null : Number(shareExpiry);
      try {
        const { payload } = await fetchJsonOrThrow<SharePayload>(
          `/memo/api/${shareMemoId}/share`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "same-origin",
            body: JSON.stringify({
              force_refresh: forceRefresh,
              expires_in_days: expiresInDays,
            }),
          },
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
    },
    [mutate, shareExpiry, shareMemoId],
  );

  const revokeShareLink = useCallback(async () => {
    if (!shareMemoId) return;
    setShareLoading(true);
    setShareStatus({ type: "success", text: "共有リンクを無効化しています..." });
    try {
      const { payload } = await fetchJsonOrThrow<SharePayload>(
        `/memo/api/${shareMemoId}/share/revoke`,
        {
          method: "POST",
          credentials: "same-origin",
        },
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
    if (!shareUrl) {
      setShareStatus({ type: "error", text: "先に共有リンクを作成してください。" });
      return;
    }
    try {
      await copyTextToClipboard(shareUrl);
      setShareStatus({ type: "success", text: "共有リンクをコピーしました。" });
    } catch (error) {
      setShareStatus({ type: "error", text: error instanceof Error ? error.message : "リンクのコピーに失敗しました。" });
    }
  }, [shareUrl]);

  const openNativeShareSheet = useCallback(async () => {
    if (!shareUrl) {
      setShareStatus({ type: "error", text: "先に共有リンクを作成してください。" });
      return;
    }
    if (!supportsNativeShare || typeof navigator.share !== "function") {
      setShareStatus({ type: "error", text: "このブラウザは端末共有に対応していません。" });
      return;
    }
    try {
      await navigator.share({
        title: MEMO_SHARE_TITLE,
        text: MEMO_SHARE_TEXT,
        url: shareUrl,
      });
    } catch (error) {
      if (error instanceof Error && error.name === "AbortError") {
        return;
      }
      setShareStatus({ type: "error", text: error instanceof Error ? error.message : "端末共有に失敗しました。" });
    }
  }, [shareUrl, supportsNativeShare]);

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
          style={{
            display: isLoggedIn ? "none" : "",
            position: "fixed",
            top: "10px",
            right: "10px",
            zIndex: "var(--z-floating-controls)",
          }}
        >
          <button
            id="login-btn"
            className="auth-btn"
            onClick={() => {
              window.location.href = "/login";
            }}
          >
            <i className="bi bi-person-circle"></i>
            <span>ログイン / 登録</span>
          </button>
        </div>

        <user-icon id="userIcon" style={{ display: isLoggedIn ? "" : "none" }}></user-icon>

        <div className="memo-container">
          <header className="memo-toolbar memo-card">
            <div className="memo-toolbar__title">
              <h1>メモワークスペース</h1>
              <p>検索・整理・共有を1ページで完結。保存した会話をすぐ再利用できます。</p>
            </div>
            <div className="memo-toolbar__search">
              <label htmlFor="memo-search" className="sr-only">メモを検索</label>
              <i className="bi bi-search" aria-hidden="true"></i>
              <input
                id="memo-search"
                type="search"
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value);
                }}
                placeholder="タイトル・タグ・本文から検索"
              />
            </div>
            <div className="memo-toolbar__filters">
              <input
                type="text"
                className="memo-toolbar__tag-filter"
                value={tagFilter}
                onChange={(event) => {
                  setTagFilter(event.target.value);
                }}
                placeholder="タグで絞り込み"
              />
              <label className="memo-toolbar__date-filter">
                <span>開始日</span>
                <input
                  type="date"
                  value={dateFrom}
                  onChange={(event) => {
                    setDateFrom(event.target.value);
                  }}
                />
              </label>
              <label className="memo-toolbar__date-filter">
                <span>終了日</span>
                <input
                  type="date"
                  value={dateTo}
                  onChange={(event) => {
                    setDateTo(event.target.value);
                  }}
                />
              </label>
              <select
                value={sortMode}
                onChange={(event) => {
                  setSortMode(event.target.value);
                }}
              >
                <option value="recent">新しい順</option>
                <option value="updated">更新順</option>
                <option value="oldest">古い順</option>
                <option value="title">タイトル順</option>
              </select>
              <select
                value={archiveScope}
                onChange={(event) => {
                  setArchiveScope(event.target.value);
                }}
              >
                <option value="active">通常メモ</option>
                <option value="all">すべて</option>
                <option value="archived">アーカイブのみ</option>
              </select>
              <button
                type="button"
                className="memo-toolbar__clear"
                onClick={() => {
                  setQuery("");
                  setTagFilter("");
                  setDateFrom("");
                  setDateTo("");
                  setArchiveScope("active");
                  setSortMode("recent");
                }}
              >
                クリア
              </button>
            </div>
            {topTags.length ? (
              <div className="memo-toolbar__chips" aria-label="人気タグ">
                {topTags.map(([tag, count]) => (
                  <button
                    type="button"
                    key={tag}
                    className={`memo-chip${tagFilter === tag ? " is-active" : ""}`}
                    onClick={() => {
                      setTagFilter((prev) => (prev === tag ? "" : tag));
                    }}
                  >
                    #{tag}
                    <span>{count}</span>
                  </button>
                ))}
              </div>
            ) : null}
          </header>

          {flashState ? <div className={`memo-flash memo-flash--${flashState.type}`}>{flashState.text}</div> : null}

          <div className="memo-mobile-tabs" role="tablist" aria-label="メモ画面タブ">
            <button
              type="button"
              role="tab"
              aria-selected={activeMobileTab === "list"}
              className={activeMobileTab === "list" ? "is-active" : ""}
              onClick={() => {
                setActiveMobileTab("list");
              }}
            >
              メモ一覧
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={activeMobileTab === "compose"}
              className={activeMobileTab === "compose" ? "is-active" : ""}
              onClick={() => {
                setActiveMobileTab("compose");
              }}
            >
              新規作成
            </button>
          </div>

          <div className={`memo-grid${activeMobileTab === "compose" ? " show-compose" : " show-list"}`}>
            <section className="memo-card memo-history-panel">
              <div className="memo-panel__header">
                <h2>メモ一覧</h2>
                <p>{totalMemoCount}件</p>
              </div>

              {memoLoadError ? (
                <div className="memo-history__empty">{memoLoadError.message}</div>
              ) : null}

              {!memoLoadError && memoListLoading && memos.length === 0 ? (
                <div className="memo-history__empty">
                  <InlineLoading label="メモを読み込んでいます..." className="mx-auto" />
                </div>
              ) : null}

              {!memoLoadError && !memoListLoading && memos.length === 0 ? (
                <div className="memo-history__empty">条件に一致するメモがありません。</div>
              ) : null}

              {memos.length ? (
                <ul className="memo-history__list">
                  {memos.map((memo) => {
                    const memoId = String(memo.id);
                    const isEditing = editingMemoId === memoId;
                    const isBusy = actionLoadingId === memoId;
                    const tags = splitTags(memo.tags);

                    return (
                      <li key={memoId}>
                        <article className={`memo-item${memo.is_archived ? " is-archived" : ""}${memo.is_pinned ? " is-pinned" : ""}`}>
                          <div className="memo-item__header">
                            <button
                              type="button"
                              className="memo-item__open"
                              onClick={() => {
                                void openMemoDetail(memoId);
                              }}
                            >
                              <div className="memo-item__heading">
                                <h3 className="memo-item__title">{memo.title || "保存したメモ"}</h3>
                                <time className="memo-item__date">
                                  {formatDateTime(memo.updated_at || memo.created_at) || memo.updated_at || memo.created_at || ""}
                                </time>
                              </div>
                            </button>
                            <div className="memo-item__status-icons" aria-label="メモ状態">
                              {memo.is_pinned ? <i className="bi bi-pin-angle-fill" title="ピン留め中"></i> : null}
                              {memo.is_archived ? <i className="bi bi-archive-fill" title="アーカイブ中"></i> : null}
                              {memo.is_active ? <i className="bi bi-link-45deg" title="共有中"></i> : null}
                            </div>
                          </div>

                          {isEditing ? (
                            <div className="memo-item__inline-edit">
                              <input
                                type="text"
                                value={quickEditTitle}
                                onChange={(event) => {
                                  setQuickEditTitle(event.target.value);
                                }}
                                placeholder="タイトル"
                                maxLength={255}
                              />
                              <input
                                type="text"
                                value={quickEditTags}
                                onChange={(event) => {
                                  setQuickEditTags(event.target.value);
                                }}
                                placeholder="タグ（スペース区切り）"
                                maxLength={255}
                              />
                              <div className="memo-item__inline-actions">
                                <button type="button" onClick={() => {
                                  void saveQuickEdit(memoId);
                                }} disabled={isBusy}>保存</button>
                                <button type="button" onClick={cancelQuickEdit} disabled={isBusy}>キャンセル</button>
                              </div>
                            </div>
                          ) : (
                            <>
                              <button
                                type="button"
                                className="memo-item__open memo-item__open--content"
                                onClick={() => {
                                  void openMemoDetail(memoId);
                                }}
                              >
                                <div className="memo-tag-list">
                                  {tags.length ? (
                                    tags.map((tag) => (
                                      <span
                                        key={tag}
                                        className="memo-tag"
                                      >
                                        {tag}
                                      </span>
                                    ))
                                  ) : (
                                    <span className="memo-tag memo-tag--muted">タグなし</span>
                                  )}
                                </div>
                                {memo.excerpt ? <MemoMarkdown text={parseMemoText(memo.excerpt)} className="memo-item__excerpt" /> : null}
                              </button>

                              <div className="memo-item__actions">
                                {tags.map((tag) => (
                                  <button
                                    type="button"
                                    key={tag}
                                    className="memo-item__tag-action"
                                    onClick={() => {
                                      setTagFilter(tag);
                                    }}
                                    disabled={isBusy}
                                    title={`${tag} で絞り込み`}
                                  >
                                    #{tag}
                                  </button>
                                ))}
                                <button
                                  type="button"
                                  className="memo-item__action"
                                  onClick={() => {
                                    void copyMemoExcerpt(memo);
                                  }}
                                  disabled={isBusy}
                                  title="要約をコピー"
                                >
                                  <i className="bi bi-files"></i>
                                </button>
                                <button
                                  type="button"
                                  className="memo-item__action"
                                  onClick={() => {
                                    startQuickEdit(memo);
                                  }}
                                  disabled={isBusy}
                                  title="タイトル・タグを編集"
                                >
                                  <i className="bi bi-pencil-square"></i>
                                </button>
                                <button
                                  type="button"
                                  className={`memo-item__action${memo.is_pinned ? " is-active" : ""}`}
                                  onClick={() => {
                                    void handleTogglePin(memo);
                                  }}
                                  disabled={isBusy}
                                  title={memo.is_pinned ? "ピン留め解除" : "ピン留め"}
                                >
                                  <i className="bi bi-pin-angle"></i>
                                </button>
                                <button
                                  type="button"
                                  className={`memo-item__action${memo.is_archived ? " is-active" : ""}`}
                                  onClick={() => {
                                    void handleToggleArchive(memo);
                                  }}
                                  disabled={isBusy}
                                  title={memo.is_archived ? "アーカイブ解除" : "アーカイブ"}
                                >
                                  <i className="bi bi-archive"></i>
                                </button>
                                <button
                                  type="button"
                                  className="memo-item__action"
                                  onClick={() => {
                                    void openShareModal(memo);
                                  }}
                                  disabled={isBusy}
                                  title="共有設定"
                                >
                                  <i className="bi bi-share"></i>
                                </button>
                                <button
                                  type="button"
                                  className="memo-item__action memo-item__action--danger"
                                  onClick={() => {
                                    void handleDeleteMemo(memo);
                                  }}
                                  disabled={isBusy}
                                  title="削除"
                                >
                                  <i className="bi bi-trash3"></i>
                                </button>
                              </div>
                            </>
                          )}
                        </article>
                      </li>
                    );
                  })}
                </ul>
              ) : null}
            </section>

            <section className="memo-card memo-compose-panel">
              <div className="memo-panel__header">
                <h2>新規メモ</h2>
                <p>AI回答は必須、他は必要に応じて入力してください。</p>
              </div>

              <form method="post" className="memo-form" onSubmit={handleSubmitMemo}>
                <div className="form-group">
                  <label htmlFor="input_content">
                    入力内容 <span className="optional">(任意)</span>
                  </label>
                  <textarea
                    id="input_content"
                    name="input_content"
                    className="memo-control"
                    value={formState.input_content}
                    onChange={handleFormChange}
                    placeholder="AIに送った入力内容"
                  />
                </div>

                <div className="form-group">
                  <label htmlFor="ai_response">AIの回答</label>
                  <textarea
                    id="ai_response"
                    name="ai_response"
                    className="memo-control memo-control--response"
                    value={formState.ai_response}
                    onChange={handleFormChange}
                    placeholder="AIからの回答"
                    required
                  />
                </div>

                <div className="form-grid">
                  <div className="form-group">
                    <label htmlFor="title">
                      タイトル <span className="optional">(任意)</span>
                    </label>
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
                    <label htmlFor="tags">
                      タグ <span className="optional">(任意)</span>
                    </label>
                    <input
                      id="tags"
                      name="tags"
                      type="text"
                      className="memo-control"
                      value={formState.tags}
                      onChange={handleFormChange}
                      maxLength={255}
                      placeholder="例: 設計 仕様"
                    />
                  </div>
                </div>

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

        <div className={`memo-modal${selectedMemo ? " is-visible" : ""}`} aria-hidden={selectedMemo ? "false" : "true"}>
          <div
            className="memo-modal__overlay"
            onClick={() => {
              setSelectedMemo(null);
            }}
          ></div>
          <div className="memo-modal__content" role="dialog" aria-modal="true" aria-labelledby="memoModalTitle">
            <button
              type="button"
              className="memo-modal__close"
              aria-label="閉じる"
              onClick={() => {
                setSelectedMemo(null);
              }}
            >
              <i className="bi bi-x-lg"></i>
            </button>
            <header className="memo-modal__header">
              <h3 id="memoModalTitle">{selectedMemo?.title || "保存したメモ"}</h3>
              <p className="memo-modal__date">{formatDateTime(selectedMemo?.updated_at || selectedMemo?.created_at) || selectedMemo?.created_at || ""}</p>
            </header>
            {detailLoading ? (
              <div className="memo-history__empty">
                <InlineLoading label="メモを読み込んでいます..." className="mx-auto" />
              </div>
            ) : null}
            {!detailLoading && detailError ? <div className="memo-history__empty">{detailError}</div> : null}
            {!detailLoading && selectedMemo ? (
              <>
                <div className="memo-modal__tags">
                  {splitTags(selectedMemo.tags).length ? splitTags(selectedMemo.tags).map((tag) => <span className="memo-tag" key={tag}>{tag}</span>) : <span className="memo-tag memo-tag--muted">タグなし</span>}
                </div>
                <div className="memo-modal__body">
                  <section className="memo-modal__section">
                    <h4>入力内容</h4>
                    <MemoMarkdown text={parseMemoText(selectedMemo.input_content)} className="memo-modal__markdown" />
                  </section>
                  <section className="memo-modal__section">
                    <h4>AIの回答</h4>
                    <MemoMarkdown text={parseMemoText(selectedMemo.ai_response)} className="memo-modal__markdown" />
                  </section>
                </div>
              </>
            ) : null}
          </div>
        </div>

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
                  onChange={(event) => {
                    setShareExpiry(event.target.value as (typeof SHARE_EXPIRES_OPTIONS)[number]["value"]);
                  }}
                  disabled={shareLoading}
                >
                  {SHARE_EXPIRES_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </div>
              <div className="memo-share-modal__actions">
                <button type="button" className="primary-button" onClick={() => {
                  void createShareLink(false);
                }} disabled={shareLoading}>
                  <i className="bi bi-link-45deg"></i>
                  作成
                </button>
                <button type="button" className="secondary-button" onClick={() => {
                  void createShareLink(true);
                }} disabled={shareLoading}>
                  <i className="bi bi-arrow-repeat"></i>
                  再生成
                </button>
                <button type="button" className="secondary-button" onClick={() => {
                  void revokeShareLink();
                }} disabled={shareLoading}>
                  <i className="bi bi-slash-circle"></i>
                  無効化
                </button>
                <button type="button" className="secondary-button" onClick={() => {
                  void copyShareLink();
                }} disabled={shareLoading || !shareUrl}>
                  <i className="bi bi-files"></i>
                  コピー
                </button>
                {supportsNativeShare ? (
                  <button type="button" className="secondary-button" onClick={() => {
                    void openNativeShareSheet();
                  }} disabled={shareLoading || !shareUrl}>
                    <i className="bi bi-box-arrow-up-right"></i>
                    端末共有
                  </button>
                ) : null}
              </div>
              {shareStatus ? <p className={`memo-share-modal__status memo-share-modal__status--${shareStatus.type}`}>{shareStatus.text}</p> : null}
              <div className="memo-share-modal__meta">
                <span>{shareState?.is_active ? "公開中" : "未公開 / 無効"}</span>
                <span>{shareState?.expires_at ? `期限: ${formatDateTime(shareState.expires_at) || shareState.expires_at}` : "期限: 無期限"}</span>
              </div>
              <div className="memo-share-modal__sns">
                <a target="_blank" rel="noopener noreferrer" href={shareSnsLinks.x}>
                  <span>X</span>
                </a>
                <a target="_blank" rel="noopener noreferrer" href={shareSnsLinks.line}>
                  <span>LINE</span>
                </a>
                <a target="_blank" rel="noopener noreferrer" href={shareSnsLinks.facebook}>
                  <span>Facebook</span>
                </a>
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
