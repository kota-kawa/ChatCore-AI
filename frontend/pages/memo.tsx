import Head from "next/head";
import type { GetServerSideProps } from "next";
import { useRouter } from "next/router";
import { useEffect, useState, type ChangeEvent, type FormEvent } from "react";

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

type MemoPageProps = {
  memos: MemoRecord[];
  saved: boolean;
};

export const getServerSideProps: GetServerSideProps<MemoPageProps> = async (context) => {
  const backendUrl = process.env.BACKEND_URL || "http://localhost:5004";
  const cookie = typeof context.req.headers.cookie === "string" ? context.req.headers.cookie : "";
  let memos: MemoRecord[] = [];

  try {
    const res = await fetch(`${backendUrl}/memo/api/recent`, {
      headers: cookie ? { cookie } : undefined
    });
    if (res.ok) {
      const data = await res.json();
      memos = Array.isArray(data.memos) ? data.memos : [];
    }
  } catch (err) {
    memos = [];
  }

  const saved = context.query.saved === "1";

  return {
    props: {
      memos,
      saved
    }
  };
};

export default function MemoPage({ memos, saved }: MemoPageProps) {
  useEffect(() => {
    document.body.classList.add("memo-page");
    import("../scripts/entries/memo");
    return () => {
      document.body.classList.remove("memo-page");
      document.body.classList.remove("modal-open");
    };
  }, []);

  const router = useRouter();
  const [formState, setFormState] = useState({
    input_content: "",
    ai_response: "",
    title: "",
    tags: ""
  });
  const [message, setMessage] = useState<MessageState | null>(
    saved ? { type: "success", text: "メモを保存しました。" } : null
  );
  const [submitting, setSubmitting] = useState(false);

  const handleChange = (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const { name, value } = event.target;
    setFormState((prev) => ({ ...prev, [name]: value }));
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
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

      router.replace("/memo?saved=1");
    } catch (error) {
      setMessage({
        type: "error",
        text: error instanceof Error ? error.message : "メモの保存に失敗しました。"
      });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <Head>
        <meta charSet="UTF-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
        <title>メモを保存</title>
        <link rel="icon" type="image/webp" href="/static/favicon.webp" />
        <link rel="icon" type="image/png" href="/static/favicon.png" />
        <link
          rel="stylesheet"
          href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.5/font/bootstrap-icons.css"
        />
      </Head>

      <div className="memo-page-shell">
        <action-menu></action-menu>

        <div className="memo-page-glow memo-page-glow--amber" aria-hidden="true"></div>
        <div className="memo-page-glow memo-page-glow--gold" aria-hidden="true"></div>

        <div id="auth-buttons" style={{ display: "none", position: "fixed", top: "10px", right: "10px", zIndex: 2000 }}>
          <button id="login-btn" className="auth-btn">
            <i className="bi bi-person-circle"></i>
            <span>ログイン / 登録</span>
          </button>
        </div>

        <user-icon id="userIcon" style={{ display: "none" }}></user-icon>

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

              {memos.length ? (
                <ul className="memo-history__list">
                  {memos.map((memo) => {
                    const displayTitle = memo.title || "無題のメモ";
                    const tagList = memo.tags ? memo.tags.split(/\s+/).filter(Boolean) : [];
                    const excerpt = memo.ai_response
                      ? memo.ai_response.slice(0, 120) + (memo.ai_response.length > 120 ? "…" : "")
                      : "";

                    return (
                      <li key={memo.id}>
                        <article
                          className="memo-item"
                          role="button"
                          tabIndex={0}
                          data-memo-id={memo.id}
                          data-title={displayTitle}
                          data-date={memo.created_at || ""}
                          data-tags={memo.tags || ""}
                          data-input={JSON.stringify(memo.input_content || "")}
                          data-response={JSON.stringify(memo.ai_response || "")}
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
                          {excerpt ? <div className="memo-item__excerpt">{excerpt}</div> : null}
                        </article>
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <div className="memo-history__empty">
                  まだ保存されたメモはありません。
                </div>
              )}
            </section>
          </div>
        </div>

        <div
          className="memo-modal"
          id="memoModal"
          aria-hidden="true"
        >
          <div
            className="memo-modal__overlay"
            data-modal-overlay
            data-close-modal
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
            >
              <svg aria-hidden="true" className="h-4 w-4" viewBox="0 0 24 24" fill="currentColor">
                <path d="M18.3 5.71 12 12l6.3 6.29-1.41 1.42L10.59 13.4 4.29 19.7 2.88 18.3 9.17 12 2.88 5.71 4.29 4.3 10.59 10.6 16.9 4.29z" />
              </svg>
            </button>
            <header className="memo-modal__header">
              <h3 id="memoModalTitle" data-modal-title>
                保存したメモ
              </h3>
              <p className="memo-modal__date" data-modal-date></p>
            </header>
            <div className="memo-modal__tags" data-modal-tags></div>
            <div className="memo-modal__body">
              <section className="memo-modal__section">
                <h4>入力内容</h4>
                <div className="memo-modal__markdown" data-modal-input></div>
              </section>
              <section className="memo-modal__section">
                <h4>AIの回答</h4>
                <div className="memo-modal__markdown" data-modal-response></div>
              </section>
            </div>
          </div>
        </div>

        <div
          className="memo-share-modal"
          id="memoShareModal"
          aria-hidden="true"
        >
          <div
            className="memo-share-modal__overlay"
            data-close-share-modal
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
              />
              <p id="memo-share-status" className="memo-share-modal__status">
                共有するメモを選択してください。
              </p>
              <div className="memo-share-modal__actions">
                <button type="button" id="memo-share-create-btn" className="primary-button">リンクを生成</button>
                <button type="button" id="memo-share-copy-btn" className="primary-button">リンクをコピー</button>
                <button type="button" id="memo-share-web-btn" className="primary-button">端末で共有</button>
              </div>
              <div className="memo-share-modal__sns">
                <a id="memo-share-sns-x" target="_blank" rel="noopener noreferrer" href="#">
                  <i className="bi bi-twitter"></i>
                  <span>X</span>
                </a>
                <a id="memo-share-sns-line" target="_blank" rel="noopener noreferrer" href="#">
                  <i className="bi bi-chat-dots"></i>
                  <span>LINE</span>
                </a>
                <a id="memo-share-sns-facebook" target="_blank" rel="noopener noreferrer" href="#">
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
