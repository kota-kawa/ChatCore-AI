import Head from "next/head";
import { useRouter } from "next/router";
import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent, type FormEvent } from "react";
import useSWR from "swr";

import "../scripts/core/csrf";
import { formatLLMOutput } from "../scripts/chat/chat_ui";
import { copyTextToClipboard, renderSanitizedHTML } from "../scripts/chat/message_utils";
import { setLoggedInState } from "../scripts/core/app_state";
import { fetchJsonOrThrow } from "../scripts/core/runtime_validation";

type MemoRecord = {
  id: number | string;
  title?: string | null;
  tags?: string | null;
  ai_response?: string | null;
  input_content?: string | null;
  created_at?: string | null;
};

type MessageState = {
  type: "success" | "error";
  text: string;
};

type MemoListResponse = {
  memos?: MemoRecord[];
  error?: string;
};

type HttpError = Error & {
  status?: number;
};

type MemoDetailState = {
  id: string;
  title: string;
  date: string;
  tags: string[];
  input: string;
  response: string;
};

type ShareStatusState = {
  text: string;
  isError: boolean;
};

const MEMO_SHARE_TITLE = "Chat Core 共有メモ";
const MEMO_SHARE_TEXT = "このメモを共有しました。";

const loadRecentMemos = async (url: string): Promise<MemoRecord[]> => {
  const res = await fetch(url, { credentials: "same-origin" });
  const data: MemoListResponse = await res.json().catch(() => ({}));

  if (res.status === 401) {
    return [];
  }

  if (!res.ok) {
    const error = new Error(data.error || `メモの取得に失敗しました (${res.status})`) as HttpError;
    error.status = res.status;
    throw error;
  }

  return Array.isArray(data.memos) ? data.memos : [];
};

function parseMemoText(raw: string | null | undefined) {
  if (!raw) return "";
  try {
    const parsed = JSON.parse(raw);
    return typeof parsed === "string" ? parsed : "";
  } catch {
    return raw;
  }
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
  const { data: memos = [], error: memoLoadError, isLoading, mutate } = useSWR<MemoRecord[]>(
    "/memo/api/recent",
    loadRecentMemos,
    {
      revalidateOnFocus: true,
      refreshInterval: 15000,
      dedupingInterval: 5000,
      keepPreviousData: true
    }
  );

  const [formState, setFormState] = useState({
    input_content: "",
    ai_response: "",
    title: "",
    tags: ""
  });
  const [message, setMessage] = useState<MessageState | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const [isLoggedIn, setIsLoggedIn] = useState(false);

  const [selectedMemo, setSelectedMemo] = useState<MemoDetailState | null>(null);
  const [isShareModalOpen, setIsShareModalOpen] = useState(false);
  const [shareUrl, setShareUrl] = useState("");
  const [shareStatus, setShareStatus] = useState<ShareStatusState>({
    text: "共有するメモを選択してください。",
    isError: false
  });
  const [shareActionLoading, setShareActionLoading] = useState(false);
  const [supportsNativeShare, setSupportsNativeShare] = useState(false);

  const shareRequestSequenceRef = useRef(0);
  const cachedShareUrlsRef = useRef<Map<string, string>>(new Map());

  useEffect(() => {
    document.body.classList.add("memo-page");

    const importCustomElements = async () => {
      await Promise.all([
        import("../scripts/components/popup_menu"),
        import("../scripts/components/user_icon")
      ]);
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
  }, [selectedMemo, isShareModalOpen]);

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
      setMessage({ type: "success", text: "メモを保存しました。" });
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

  const handleChange = useCallback((event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const { name, value } = event.target;
    setFormState((prev) => ({ ...prev, [name]: value }));
  }, []);

  const handleSubmit = useCallback(async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setMessage(null);

    if (!formState.ai_response.trim()) {
      setMessage({ type: "error", text: "AIの回答を入力してください。" });
      return;
    }

    setSubmitting(true);
    try {
      const res = await fetch("/memo/api", {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        credentials: "same-origin",
        body: JSON.stringify({
          input_content: formState.input_content,
          ai_response: formState.ai_response,
          title: formState.title,
          tags: formState.tags
        })
      });

      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.status === "fail") {
        throw new Error(data.error || "メモの保存に失敗しました。");
      }

      setFormState({
        input_content: "",
        ai_response: "",
        title: "",
        tags: ""
      });
      setMessage({ type: "success", text: "メモを保存しました。" });
      void router.replace("/memo?saved=1", undefined, { shallow: true });
      void mutate();
    } catch (error) {
      setMessage({
        type: "error",
        text: error instanceof Error ? error.message : "メモの保存に失敗しました。"
      });
    } finally {
      setSubmitting(false);
    }
  }, [formState, mutate, router]);

  const openMemoDetail = useCallback((memo: MemoRecord) => {
    const tagString = memo.tags || "";
    const tags = tagString
      .split(/\s+/)
      .map((tag) => tag.trim())
      .filter(Boolean);

    setSelectedMemo({
      id: String(memo.id),
      title: memo.title || "保存したメモ",
      date: memo.created_at || "",
      tags,
      input: parseMemoText(memo.input_content),
      response: parseMemoText(memo.ai_response)
    });
  }, []);

  const updateShareStatus = useCallback((text: string, isError = false) => {
    setShareStatus({ text, isError });
  }, []);

  const createShareLink = useCallback(async (memoId: string, forceRefresh = false) => {
    if (!memoId) {
      setShareUrl("");
      updateShareStatus("共有するメモを選択してください。", true);
      return;
    }

    if (!forceRefresh && cachedShareUrlsRef.current.has(memoId)) {
      setShareUrl(cachedShareUrlsRef.current.get(memoId) || "");
      updateShareStatus("共有リンクを表示しています。");
      return;
    }

    const requestId = shareRequestSequenceRef.current + 1;
    shareRequestSequenceRef.current = requestId;

    setShareActionLoading(true);
    updateShareStatus("共有リンクを生成しています...");

    try {
      const { payload } = await fetchJsonOrThrow<Record<string, unknown>>(
        "/memo/api/share",
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json"
          },
          credentials: "same-origin",
          body: JSON.stringify({ memo_id: Number(memoId) })
        },
        {
          defaultMessage: "共有リンクの作成に失敗しました。",
          hasApplicationError: (data) => typeof data.share_url !== "string" || !data.share_url.trim()
        }
      );

      if (shareRequestSequenceRef.current !== requestId) {
        return;
      }

      const createdShareUrl = typeof payload.share_url === "string" ? payload.share_url : "";
      cachedShareUrlsRef.current.set(memoId, createdShareUrl);
      setShareUrl(createdShareUrl);
      updateShareStatus("共有リンクを作成しました。");
    } catch (error) {
      if (shareRequestSequenceRef.current !== requestId) {
        return;
      }
      updateShareStatus(error instanceof Error ? error.message : String(error), true);
    } finally {
      if (shareRequestSequenceRef.current === requestId) {
        setShareActionLoading(false);
      }
    }
  }, [updateShareStatus]);

  const openShareModal = useCallback((memo: MemoRecord) => {
    const memoId = String(memo.id || "");
    if (!memoId) {
      updateShareStatus("共有対象のメモが見つかりません。", true);
      return;
    }

    setShareUrl("");
    updateShareStatus("共有リンクを生成しています...");
    setIsShareModalOpen(true);
    void createShareLink(memoId, false);
  }, [createShareLink, updateShareStatus]);

  const closeShareModal = useCallback(() => {
    setIsShareModalOpen(false);
  }, []);

  const handleCopyShareLink = useCallback(async () => {
    if (!shareUrl.trim()) {
      updateShareStatus("先に共有リンクを生成してください。", true);
      return;
    }

    try {
      await copyTextToClipboard(shareUrl);
      updateShareStatus("リンクをコピーしました。");
    } catch (error) {
      updateShareStatus(error instanceof Error ? error.message : String(error), true);
    }
  }, [shareUrl, updateShareStatus]);

  const handleNativeShare = useCallback(async () => {
    if (!shareUrl.trim()) {
      updateShareStatus("先に共有リンクを生成してください。", true);
      return;
    }

    if (!supportsNativeShare || typeof navigator.share !== "function") {
      updateShareStatus("このブラウザはネイティブ共有に対応していません。", true);
      return;
    }

    try {
      await navigator.share({
        title: MEMO_SHARE_TITLE,
        text: MEMO_SHARE_TEXT,
        url: shareUrl
      });
      updateShareStatus("共有シートを開きました。");
    } catch (error) {
      if (error instanceof Error && error.name === "AbortError") {
        return;
      }
      updateShareStatus(error instanceof Error ? error.message : String(error), true);
    }
  }, [shareUrl, supportsNativeShare, updateShareStatus]);

  const shareSnsLinks = useMemo(() => {
    if (!shareUrl) {
      return {
        x: "#",
        line: "#",
        facebook: "#"
      };
    }
    const encodedUrl = encodeURIComponent(shareUrl);
    const encodedText = encodeURIComponent(MEMO_SHARE_TEXT);
    return {
      x: `https://twitter.com/intent/tweet?url=${encodedUrl}&text=${encodedText}`,
      line: `https://social-plugins.line.me/lineit/share?url=${encodedUrl}`,
      facebook: `https://www.facebook.com/sharer/sharer.php?u=${encodedUrl}`
    };
  }, [shareUrl]);

  return (
    <>
      <Head>
        <meta charSet="UTF-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
        <title>メモを保存</title>
        <link rel="icon" type="image/webp" href="/static/favicon.webp" />
        <link rel="icon" type="image/png" href="/static/favicon.png" />
      </Head>

      <div className="memo-page-shell">
        <action-menu></action-menu>

        <div className="memo-page-glow memo-page-glow--amber" aria-hidden="true"></div>
        <div className="memo-page-glow memo-page-glow--gold" aria-hidden="true"></div>

        <div
          id="auth-buttons"
          style={{
            display: isLoggedIn ? "none" : "",
            position: "fixed",
            top: "10px",
            right: "10px",
            zIndex: 2000
          }}
        >
          <button id="login-btn" className="auth-btn" onClick={() => {
            window.location.href = "/login";
          }}>
            <i className="bi bi-person-circle"></i>
            <span>ログイン / 登録</span>
          </button>
        </div>

        <user-icon id="userIcon" style={{ display: isLoggedIn ? "" : "none" }}></user-icon>

        <div className="memo-container">
          <header className="memo-hero memo-card">
            <div className="memo-hero__topline">
              <span className="memo-hero__icon">
                <i className="bi bi-journal-text"></i>
              </span>
              <div className="memo-hero__text">
                <p className="memo-hero__eyebrow">
                  Memo Workspace
                </p>
                <h1>
                  会話メモを整理する
                </h1>
                <p>
                  AIとのやり取りを保存し、後から素早く振り返りましょう。入力とAIの回答をそのまま記録できます。
                </p>
              </div>
            </div>
            <div className="memo-hero__chips" aria-label="主な機能">
              <span className="memo-hero__chip">
                <i className="bi bi-tags"></i>
                タグで整理
              </span>
              <span className="memo-hero__chip">
                <i className="bi bi-lightning-charge"></i>
                すばやく検索
              </span>
              <span className="memo-hero__chip">
                <i className="bi bi-shield-check"></i>
                安心の保存
              </span>
            </div>
          </header>

          <div className="memo-grid">
            <section className="memo-card memo-card--form">
              <div className="memo-card__header">
                <h2>新しいメモを追加</h2>
                <p>
                  入力内容とAIの回答を貼り付けて保存します。
                </p>
              </div>

              {message ? (
                <div className={`memo-flash memo-flash--${message.type}`} role="alert">
                  {message.text}
                </div>
              ) : null}

              <form method="post" className="memo-form" onSubmit={handleSubmit}>
                <div className="form-group">
                  <label htmlFor="input_content">
                    入力内容 <span className="optional">(任意)</span>
                  </label>
                  <textarea
                    id="input_content"
                    name="input_content"
                    placeholder="AIに送ったプロンプトを入力 / 貼り付けしてください"
                    className="memo-control"
                    value={formState.input_content}
                    onChange={handleChange}
                  />
                </div>

                <div className="form-group">
                  <label htmlFor="ai_response">
                    AIの回答
                  </label>
                  <textarea
                    id="ai_response"
                    name="ai_response"
                    placeholder="AIからの回答を入力 / 貼り付けしてください"
                    required
                    className="memo-control memo-control--response"
                    value={formState.ai_response}
                    onChange={handleChange}
                  />
                </div>

                <div className="form-grid">
                  <div className="form-group">
                    <label htmlFor="title">
                      タイトル <span className="optional">(任意)</span>
                    </label>
                    <input
                      type="text"
                      id="title"
                      name="title"
                      placeholder="空の場合は回答の1行目が使われます"
                      className="memo-control"
                      value={formState.title}
                      onChange={handleChange}
                      maxLength={255}
                    />
                  </div>
                  <div className="form-group">
                    <label htmlFor="tags">
                      タグ <span className="optional">(任意・スペース区切り)</span>
                    </label>
                    <input
                      type="text"
                      id="tags"
                      name="tags"
                      placeholder="例: 仕事 議事録"
                      className="memo-control"
                      value={formState.tags}
                      onChange={handleChange}
                      maxLength={255}
                    />
                  </div>
                </div>

                <div className="form-actions">
                  <p className="memo-form__hint">必須項目はAIの回答のみです。</p>
                  <button
                    type="submit"
                    className="primary-button"
                    disabled={submitting}
                  >
                    <svg
                      aria-hidden="true"
                      className="h-4 w-4"
                      viewBox="0 0 24 24"
                      fill="currentColor"
                    >
                      <path d="M17 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V7l-4-4zm0 2l2 2h-2V5zm-2 13H7v-2h8v2zm0-4H7v-2h8v2zm0-4H7V8h8v2z" />
                    </svg>
                    保存する
                  </button>
                </div>
              </form>
            </section>

            <section className="memo-card memo-history">
              <div className="memo-card__header memo-card__header--compact">
                <h2>最近保存したメモ</h2>
                <p>メモをクリックすると内容が表示されます。</p>
              </div>

              {memoLoadError ? (
                <div className="memo-history__empty">
                  {memoLoadError.message}
                </div>
              ) : null}

              {!memoLoadError && isLoading && memos.length === 0 ? (
                <div className="memo-history__empty">
                  メモを読み込んでいます...
                </div>
              ) : null}

              {memos.length ? (
                <ul className="memo-history__list">
                  {memos.map((memo) => {
                    const displayTitle = memo.title || "無題のメモ";
                    const tagList = memo.tags ? memo.tags.split(/\s+/).filter(Boolean) : [];
                    const rawResponse = parseMemoText(memo.ai_response);
                    const excerpt = rawResponse
                      ? rawResponse.slice(0, 120) + (rawResponse.length > 120 ? "…" : "")
                      : "";

                    return (
                      <li key={memo.id}>
                        <article
                          className="memo-item"
                          role="button"
                          tabIndex={0}
                          onClick={() => {
                            openMemoDetail(memo);
                          }}
                          onKeyDown={(event) => {
                            if (event.key !== "Enter" && event.key !== " ") return;
                            event.preventDefault();
                            openMemoDetail(memo);
                          }}
                        >
                          <div className="memo-item__header">
                            <div className="memo-item__heading">
                              <h3 className="memo-item__title">
                                {displayTitle}
                              </h3>
                              {memo.created_at ? (
                                <time className="memo-item__date">{memo.created_at}</time>
                              ) : null}
                            </div>
                            <button
                              type="button"
                              className="memo-item__share"
                              data-share-memo
                              data-tooltip="このメモを共有"
                              data-tooltip-placement="top"
                              aria-label="このメモを共有"
                              onClick={(event) => {
                                event.stopPropagation();
                                openShareModal(memo);
                              }}
                            >
                              <i className="bi bi-share"></i>
                            </button>
                          </div>
                          <div className="memo-tag-list">
                            {tagList.length ? (
                              tagList.map((tag) => (
                                <span className="memo-tag" key={tag}>
                                  {tag}
                                </span>
                              ))
                            ) : (
                              <span className="memo-tag memo-tag--muted">
                                タグなし
                              </span>
                            )}
                          </div>
                          {excerpt ? (
                            <MemoMarkdown text={excerpt} className="memo-item__excerpt" />
                          ) : null}
                        </article>
                      </li>
                    );
                  })}
                </ul>
              ) : !memoLoadError && !isLoading ? (
                <div className="memo-history__empty">
                  まだ保存されたメモはありません。
                </div>
              ) : null}
            </section>
          </div>
        </div>

        <div
          className={`memo-modal${selectedMemo ? " is-visible" : ""}`}
          id="memoModal"
          aria-hidden={selectedMemo ? "false" : "true"}
        >
          <div
            className="memo-modal__overlay"
            data-modal-overlay
            data-close-modal
            onClick={() => {
              setSelectedMemo(null);
            }}
          ></div>
          <div
            className="memo-modal__content"
            role="dialog"
            aria-modal="true"
            aria-labelledby="memoModalTitle"
            data-modal-content
          >
            <button
              type="button"
              className="memo-modal__close"
              data-close-modal
              aria-label="閉じる"
              onClick={() => {
                setSelectedMemo(null);
              }}
            >
              <svg aria-hidden="true" className="h-4 w-4" viewBox="0 0 24 24" fill="currentColor">
                <path d="M18.3 5.71 12 12l6.3 6.29-1.41 1.42L10.59 13.4 4.29 19.7 2.88 18.3 9.17 12 2.88 5.71 4.29 4.3 10.59 10.6 16.9 4.29z" />
              </svg>
            </button>
            <header className="memo-modal__header">
              <h3 id="memoModalTitle" data-modal-title>
                {selectedMemo?.title || "保存したメモ"}
              </h3>
              <p className="memo-modal__date" data-modal-date>{selectedMemo?.date || ""}</p>
            </header>
            <div className="memo-modal__tags" data-modal-tags>
              {(selectedMemo?.tags || []).length > 0
                ? selectedMemo?.tags.map((tag) => (
                  <span className="memo-tag" key={tag}>{tag}</span>
                ))
                : <span className="memo-tag memo-tag--muted">タグなし</span>}
            </div>
            <div className="memo-modal__body">
              <section className="memo-modal__section">
                <h4>入力内容</h4>
                <MemoMarkdown text={selectedMemo?.input || ""} className="memo-modal__markdown" />
              </section>
              <section className="memo-modal__section">
                <h4>AIの回答</h4>
                <MemoMarkdown text={selectedMemo?.response || ""} className="memo-modal__markdown" />
              </section>
            </div>
          </div>
        </div>

        <div
          className={`memo-share-modal${isShareModalOpen ? " is-visible" : ""}`}
          id="memoShareModal"
          aria-hidden={isShareModalOpen ? "false" : "true"}
        >
          <div
            className="memo-share-modal__overlay"
            data-close-share-modal
            onClick={closeShareModal}
          ></div>
          <div
            className="memo-share-modal__content"
            role="dialog"
            aria-modal="true"
            aria-labelledby="memoShareModalTitle"
          >
            <button
              type="button"
              className="memo-share-modal__close"
              data-close-share-modal
              aria-label="閉じる"
              onClick={closeShareModal}
            >
              <svg aria-hidden="true" className="h-4 w-4" viewBox="0 0 24 24" fill="currentColor">
                <path d="M18.3 5.71 12 12l6.3 6.29-1.41 1.42L10.59 13.4 4.29 19.7 2.88 18.3 9.17 12 2.88 5.71 4.29 4.3 10.59 10.6 16.9 4.29z" />
              </svg>
            </button>
            <header className="memo-share-modal__header">
              <h3 id="memoShareModalTitle">メモを共有</h3>
              <p>このメモ専用のURLをコピーしたり、そのまま共有できます。</p>
            </header>
            <div className="memo-share-modal__body">
              <input
                type="text"
                id="memo-share-link-input"
                readOnly
                placeholder="共有リンクを準備しています"
                value={shareUrl}
              />
              <p
                id="memo-share-status"
                className={`memo-share-modal__status${shareStatus.isError ? " memo-share-modal__status--error" : ""}`}
              >
                {shareStatus.text}
              </p>
              <div className="memo-share-modal__actions">
                <button
                  type="button"
                  id="memo-share-copy-btn"
                  className="primary-button memo-share-icon-btn"
                  aria-label="リンクをコピー"
                  title="リンクをコピー"
                  onClick={() => {
                    void handleCopyShareLink();
                  }}
                  disabled={shareActionLoading}
                >
                  <i className="bi bi-files" aria-hidden="true"></i>
                </button>
                {supportsNativeShare ? (
                  <button
                    type="button"
                    id="memo-share-web-btn"
                    className="primary-button memo-share-icon-btn"
                    aria-label="端末で共有"
                    title="端末で共有"
                    onClick={() => {
                      void handleNativeShare();
                    }}
                    disabled={shareActionLoading}
                  >
                    <i className="bi bi-box-arrow-up-right" aria-hidden="true"></i>
                  </button>
                ) : null}
              </div>
              <div className="memo-share-modal__sns">
                <a id="memo-share-sns-x" target="_blank" rel="noopener noreferrer" href={shareSnsLinks.x}>
                  <svg className="share-x-icon" viewBox="0 0 24 24" aria-hidden="true">
                    <path fill="currentColor" d="M18.901 1.153h3.68l-8.04 9.188L24 22.847h-7.406l-5.8-7.584-6.63 7.584H.48l8.6-9.83L0 1.154h7.594l5.243 6.932L18.901 1.153Zm-1.291 19.49h2.039L6.486 3.24H4.298L17.61 20.643Z"></path>
                  </svg>
                  <span>X</span>
                </a>
                <a id="memo-share-sns-line" target="_blank" rel="noopener noreferrer" href={shareSnsLinks.line}>
                  <i className="bi bi-chat-dots"></i>
                  <span>LINE</span>
                </a>
                <a id="memo-share-sns-facebook" target="_blank" rel="noopener noreferrer" href={shareSnsLinks.facebook}>
                  <i className="bi bi-facebook"></i>
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
