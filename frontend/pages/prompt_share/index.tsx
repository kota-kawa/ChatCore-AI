import Head from "next/head";
import { useEffect } from "react";

type PromptCategory = {
  value: string;
  iconClass: string;
  label: string;
  active?: boolean;
};

const PROMPT_CATEGORIES: PromptCategory[] = [
  { value: "all", iconClass: "bi bi-grid", label: "全て", active: true },
  { value: "恋愛", iconClass: "bi bi-heart-fill", label: "恋愛" },
  { value: "勉強", iconClass: "bi bi-book", label: "勉強" },
  { value: "趣味", iconClass: "bi bi-camera", label: "趣味" },
  { value: "仕事", iconClass: "bi bi-briefcase", label: "仕事" },
  { value: "その他", iconClass: "bi bi-stars", label: "その他" },
  { value: "スポーツ", iconClass: "bi bi-trophy", label: "スポーツ" },
  { value: "音楽", iconClass: "bi bi-music-note", label: "音楽" },
  { value: "旅行", iconClass: "bi bi-geo-alt", label: "旅行" },
  { value: "グルメ", iconClass: "bi bi-shop", label: "グルメ" }
];

const PROMPT_CATEGORY_OPTIONS = [
  "未選択",
  "恋愛",
  "勉強",
  "趣味",
  "仕事",
  "その他",
  "スポーツ",
  "音楽",
  "旅行",
  "グルメ"
];

function PromptShareHeader() {
  return (
    <header className="prompts-header" aria-labelledby="promptShareHeroTitle">
      <div className="prompts-header__inner">
        <p className="hero-kicker">Prompt Share</p>
        <h1 id="promptShareHeroTitle" className="hero-title">
          必要なプロンプトを、すぐ検索。
        </h1>
        <p className="hero-description">
          シンプルな検索で公開プロンプトを見つけて、そのまま保存・共有できます。
        </p>

        <div className="search-section" role="search" aria-label="プロンプト検索">
          <div className="search-box">
            <input type="text" id="searchInput" placeholder="キーワードでプロンプトを検索..." />
            <button
              id="searchButton"
              type="button"
              aria-label="検索を実行する"
              data-tooltip="入力したキーワードで検索"
              data-tooltip-placement="bottom"
            >
              <i className="bi bi-search"></i>
            </button>
          </div>
        </div>

        <div className="hero-actions">
          <button type="button" id="heroOpenPostModal" className="hero-action hero-action--primary">
            <i className="bi bi-plus-lg"></i>
            <span>プロンプトを投稿</span>
          </button>
        </div>
      </div>
    </header>
  );
}

function CategorySection() {
  return (
    <section className="categories" aria-labelledby="categories-title">
      <div className="section-header section-header--compact">
        <h2 id="categories-title">カテゴリ</h2>
      </div>

      <div className="category-list">
        {PROMPT_CATEGORIES.map((category) => (
          <button
            key={category.value}
            type="button"
            className={`category-card${category.active ? " active" : ""}`}
            data-category={category.value}
          >
            <i className={category.iconClass}></i>
            <span>{category.label}</span>
          </button>
        ))}
      </div>
    </section>
  );
}

function PromptFeedSection() {
  return (
    <section id="prompt-feed-section" className="prompts-list" aria-labelledby="selected-category-title">
      <div className="section-header prompts-list-header section-header--compact">
        <h2 id="selected-category-title">全てのプロンプト</h2>
      </div>

      <div className="prompt-toolbar">
        <p id="promptCountMeta" className="prompt-count-meta">
          公開プロンプトを読み込み中...
        </p>
      </div>

      <div id="promptResults"></div>

      <div className="prompt-cards">
        <p className="prompt-loading-message">読み込み中...</p>
      </div>
    </section>
  );
}

function PromptPostModal() {
  return (
    <div
      id="postModal"
      className="post-modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="postModalTitle"
      aria-hidden="true"
    >
      <div className="post-modal-content post-modal-content--composer" tabIndex={-1}>
        <button type="button" className="close-btn" aria-label="投稿モーダルを閉じる">
          &times;
        </button>

        <div className="post-modal-scroll">
          <div className="composer-hero">
            <div className="composer-hero__copy">
              <p className="composer-hero__eyebrow">Prompt Share Composer</p>
              <h2 id="postModalTitle">新しいプロンプトを投稿</h2>
              <p className="post-modal-lead">
                AI 補助を使いながら、公開用の見やすさと使いやすさまでその場で仕上げます。
              </p>
            </div>
            <div className="composer-hero__chips" aria-hidden="true">
              <span>Searchable</span>
              <span>Polished</span>
              <span>Share Ready</span>
            </div>
          </div>

          <form className="post-form" id="postForm">
            <div className="form-group">
              <label>投稿タイプ</label>
              <div className="prompt-type-toggle" role="radiogroup" aria-label="投稿タイプを選択">
                <label className="prompt-type-option prompt-type-option--active">
                  <input type="radio" name="prompt-type" value="text" defaultChecked />
                  <span className="prompt-type-option__icon">
                    <i className="bi bi-chat-square-text"></i>
                  </span>
                  <span className="prompt-type-option__body">
                    <strong>通常プロンプト</strong>
                    <small>文章生成、要約、相談、分析など</small>
                  </span>
                </label>

                <label className="prompt-type-option">
                  <input type="radio" name="prompt-type" value="image" />
                  <span className="prompt-type-option__icon">
                    <i className="bi bi-image"></i>
                  </span>
                  <span className="prompt-type-option__body">
                    <strong>画像生成プロンプト</strong>
                    <small>Midjourney、Stable Diffusion、Flux など向け</small>
                  </span>
                </label>
              </div>
            </div>

            <div className="form-group">
              <label htmlFor="prompt-title">タイトル</label>
              <input type="text" id="prompt-title" placeholder="プロンプトのタイトルを入力" required />
            </div>

            <div className="form-group">
              <label htmlFor="prompt-category">カテゴリ</label>
              <select id="prompt-category" required defaultValue="未選択">
                {PROMPT_CATEGORY_OPTIONS.map((category) => (
                  <option key={category} value={category}>
                    {category}
                  </option>
                ))}
              </select>
            </div>

            <div className="form-group">
              <label htmlFor="prompt-content">プロンプト内容</label>
              <textarea
                id="prompt-content"
                rows={5}
                placeholder="具体的なプロンプト内容を入力"
                required
              ></textarea>
            </div>

            <div id="sharedPromptAssistRoot"></div>
            <p id="promptPostStatus" className="composer-status" hidden></p>

            <div className="form-group">
              <label htmlFor="prompt-author">投稿者名</label>
              <input type="text" id="prompt-author" placeholder="ニックネームなど" required />
            </div>

            <div className="form-group">
              <label htmlFor="prompt-ai-model">使用AIモデル（任意）</label>
              <select id="prompt-ai-model" defaultValue="">
                <option value="">未設定</option>
                <optgroup label="OpenAI">
                  <option value="ChatGPT (GPT-5.4)">ChatGPT (GPT-5.4)</option>
                  <option value="ChatGPT (GPT-5.4 mini)">ChatGPT (GPT-5.4 mini)</option>
                  <option value="ChatGPT (o3)">ChatGPT (o3)</option>
                  <option value="ChatGPT (GPT-4o)">ChatGPT (GPT-4o)</option>
                </optgroup>
                <optgroup label="Anthropic">
                  <option value="Claude Opus 4.6">Claude Opus 4.6</option>
                  <option value="Claude Sonnet 4.6">Claude Sonnet 4.6</option>
                  <option value="Claude Haiku 4.5">Claude Haiku 4.5</option>
                  <option value="Claude 3.7 Sonnet">Claude 3.7 Sonnet</option>
                </optgroup>
                <optgroup label="Google">
                  <option value="Gemini 3.1 Pro">Gemini 3.1 Pro</option>
                  <option value="Gemini 3.1 Flash">Gemini 3.1 Flash</option>
                  <option value="Gemini 2.0 Flash">Gemini 2.0 Flash</option>
                </optgroup>
                <optgroup label="Meta">
                  <option value="Llama 4 Maverick">Llama 4 Maverick</option>
                  <option value="Llama 4 Scout">Llama 4 Scout</option>
                </optgroup>
                <optgroup label="DeepSeek">
                  <option value="DeepSeek-R1">DeepSeek-R1</option>
                  <option value="DeepSeek-V3">DeepSeek-V3</option>
                </optgroup>
                <optgroup label="xAI">
                  <option value="Grok 3">Grok 3</option>
                </optgroup>
                <optgroup label="画像生成">
                  <option value="Midjourney">Midjourney</option>
                  <option value="Stable Diffusion">Stable Diffusion</option>
                  <option value="FLUX">FLUX</option>
                  <option value="DALL-E 3">DALL-E 3</option>
                </optgroup>
                <option value="その他">その他</option>
              </select>
            </div>

            <div id="imagePromptFields" className="image-prompt-fields" hidden>
              <div className="form-group">
                <label htmlFor="prompt-reference-image">作例画像（任意・1枚）</label>
                <label className="image-upload-field" htmlFor="prompt-reference-image">
                  <input
                    type="file"
                    id="prompt-reference-image"
                    accept="image/png,image/jpeg,image/webp,image/gif"
                  />
                  <span className="image-upload-field__icon">
                    <i className="bi bi-cloud-arrow-up"></i>
                  </span>
                  <span className="image-upload-field__copy">
                    <strong>画像をアップロード</strong>
                    <small>PNG / JPG / WebP / GIF、5MBまで、1枚のみ</small>
                  </span>
                </label>

                <div id="promptImagePreview" className="prompt-image-preview" hidden>
                  <img id="promptImagePreviewImg" src="" alt="アップロード画像のプレビュー" />
                  <div className="prompt-image-preview__meta">
                    <span id="promptImagePreviewName"></span>
                    <button type="button" id="promptImageClearButton" className="prompt-image-clear-btn">
                      <i className="bi bi-x-lg"></i>
                      <span>画像を外す</span>
                    </button>
                  </div>
                </div>
              </div>
            </div>

            <div className="form-group form-group--toggle">
              <label className="composer-toggle" htmlFor="guardrail-checkbox">
                <input type="checkbox" id="guardrail-checkbox" />
                <span className="composer-toggle__copy">
                  <strong>入出力例を追加する</strong>
                  <small>
                    保存・再利用しやすい投稿にするため、プロンプトの使い方を例で添えます。
                  </small>
                </span>
              </label>
            </div>

            <div id="guardrail-fields" style={{ display: "none" }}>
              <div className="form-group">
                <label htmlFor="prompt-input-example">入力例（プロンプト内容とは別にしてください）</label>
                <textarea
                  id="prompt-input-example"
                  rows={3}
                  placeholder="例: 夏休みの思い出をテーマにした短いエッセイを書いてください。"
                ></textarea>
              </div>
              <div className="form-group">
                <label htmlFor="prompt-output-example">出力例</label>
                <textarea
                  id="prompt-output-example"
                  rows={3}
                  placeholder="例: 夏休みのある日、私は家族と一緒に海辺へ出かけました。波の音と潮風に包まれながら、子供の頃の記憶がよみがえり、心が温かくなりました。その日は一生忘れられない、宝物のような時間となりました。"
                ></textarea>
              </div>
            </div>

            <button type="submit" className="submit-btn">
              <i className="bi bi-upload"></i> 投稿する
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}

function PromptDetailModal() {
  return (
    <div
      id="promptDetailModal"
      className="post-modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="modalPromptTitle"
      aria-hidden="true"
    >
      <div className="post-modal-content" tabIndex={-1}>
        <button
          type="button"
          className="close-btn"
          id="closePromptDetailModal"
          aria-label="詳細モーダルを閉じる"
        >
          &times;
        </button>
        <h2 id="modalPromptTitle">プロンプト詳細</h2>

        <div className="modal-content-body">
          <div className="form-group">
            <label>
              <strong>タイプ:</strong>
            </label>
            <p id="modalPromptType"></p>
          </div>

          <div id="modalReferenceImageGroup" className="form-group" style={{ display: "none" }}>
            <label>
              <strong>作例画像:</strong>
            </label>
            <div className="modal-reference-image">
              <img id="modalReferenceImage" src="" alt="作例画像" />
            </div>
          </div>

          <div className="form-group">
            <label>
              <strong>カテゴリ:</strong>
            </label>
            <p id="modalPromptCategory"></p>
          </div>

          <div className="form-group">
            <label>
              <strong>内容:</strong>
            </label>
            <p id="modalPromptContent"></p>
          </div>

          <div className="form-group">
            <label>
              <strong>投稿者:</strong>
            </label>
            <p id="modalPromptAuthor"></p>
          </div>

          <div id="modalAiModelGroup" className="form-group" style={{ display: "none" }}>
            <label>
              <strong>使用AIモデル:</strong>
            </label>
            <p id="modalAiModel"></p>
          </div>

          <div id="modalInputExamplesGroup" className="form-group" style={{ display: "none" }}>
            <label>
              <strong>入力例:</strong>
            </label>
            <p id="modalInputExamples"></p>
          </div>

          <div id="modalOutputExamplesGroup" className="form-group" style={{ display: "none" }}>
            <label>
              <strong>出力例:</strong>
            </label>
            <p id="modalOutputExamples"></p>
          </div>
        </div>
      </div>
    </div>
  );
}

function PromptShareModal() {
  return (
    <div
      id="promptShareModal"
      className="post-modal prompt-share-modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="promptShareModalTitle"
      aria-hidden="true"
    >
      <div className="post-modal-content prompt-share-dialog" tabIndex={-1}>
        <button
          type="button"
          className="close-btn"
          id="closePromptShareModal"
          aria-label="共有モーダルを閉じる"
        >
          &times;
        </button>

        <h2 id="promptShareModalTitle">プロンプトを共有</h2>
        <p className="prompt-share-dialog__lead">
          このプロンプト専用のURLをコピーしたり、そのまま共有できます。
        </p>

        <div className="prompt-share-dialog__row">
          <input
            type="text"
            id="prompt-share-link-input"
            readOnly
            placeholder="共有リンクを準備しています"
          />
        </div>

        <p id="prompt-share-status" className="prompt-share-dialog__status">
          共有するプロンプトを選択してください。
        </p>

        <div className="prompt-share-dialog__actions">
          <button
            type="button"
            id="prompt-share-copy-btn"
            className="submit-btn prompt-share-icon-btn"
            aria-label="リンクをコピー"
            title="リンクをコピー"
          >
            <i className="bi bi-files" aria-hidden="true"></i>
          </button>
          <button
            type="button"
            id="prompt-share-web-btn"
            className="submit-btn prompt-share-icon-btn"
            aria-label="端末で共有"
            title="端末で共有"
          >
            <i className="bi bi-box-arrow-up-right" aria-hidden="true"></i>
          </button>
        </div>

        <div className="prompt-share-dialog__sns">
          <a id="prompt-share-sns-x" target="_blank" rel="noopener noreferrer" href="#">
            <svg className="share-x-icon" viewBox="0 0 24 24" aria-hidden="true">
              <path
                fill="currentColor"
                d="M18.901 1.153h3.68l-8.04 9.188L24 22.847h-7.406l-5.8-7.584-6.63 7.584H.48l8.6-9.83L0 1.154h7.594l5.243 6.932L18.901 1.153Zm-1.291 19.49h2.039L6.486 3.24H4.298L17.61 20.643Z"
              ></path>
            </svg>
            <span>X</span>
          </a>
          <a id="prompt-share-sns-line" target="_blank" rel="noopener noreferrer" href="#">
            <i className="bi bi-chat-dots"></i>
            <span>LINE</span>
          </a>
          <a id="prompt-share-sns-facebook" target="_blank" rel="noopener noreferrer" href="#">
            <i className="bi bi-facebook"></i>
            <span>Facebook</span>
          </a>
        </div>
      </div>
    </div>
  );
}

function PromptSharePageContent() {
  return (
    <>
      <action-menu></action-menu>

      <div
        id="auth-buttons"
        style={{ display: "none", position: "fixed", top: 10, right: 10, zIndex: 2000 }}
      >
        <button id="login-btn" className="auth-btn">
          <i className="bi bi-person-circle"></i>
          <span>ログイン / 登録</span>
        </button>
      </div>

      <user-icon id="userIcon" style={{ display: "none" }}></user-icon>

      <PromptShareHeader />

      <main>
        <CategorySection />
        <PromptFeedSection />
      </main>

      <PromptPostModal />
      <PromptDetailModal />
      <PromptShareModal />

      <button
        id="openPostModal"
        className="new-prompt-btn"
        aria-label="新しいプロンプトを投稿"
        data-tooltip="新しいプロンプトを投稿"
        data-tooltip-placement="left"
      >
        <i className="bi bi-plus-lg"></i>
      </button>
    </>
  );
}

export default function PromptSharePage() {
  useEffect(() => {
    document.body.classList.add("prompt-share-page");
    const w = window as Window & {
      requestIdleCallback?: (callback: () => void, options?: { timeout: number }) => number;
      cancelIdleCallback?: (id: number) => void;
    };
    let setupTimerId: number | null = null;
    let idleId: number | null = null;

    if (typeof w.requestIdleCallback === "function") {
      idleId = w.requestIdleCallback(
        () => {
          void import("../../scripts/entries/prompt_share");
        },
        { timeout: 500 }
      );
    } else {
      setupTimerId = window.setTimeout(() => {
        void import("../../scripts/entries/prompt_share");
      }, 0);
    }

    return () => {
      if (idleId !== null && typeof w.cancelIdleCallback === "function") {
        w.cancelIdleCallback(idleId);
      }
      if (setupTimerId !== null) {
        clearTimeout(setupTimerId);
      }
      document.documentElement.classList.remove("ps-modal-open");
      document.body.classList.remove("ps-modal-open");
      document.body.style.position = "";
      document.body.style.top = "";
      document.body.style.left = "";
      document.body.style.right = "";
      document.body.style.width = "";
      document.body.classList.remove("prompt-share-page");
    };
  }, []);

  return (
    <>
      <Head>
        <meta charSet="UTF-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
        <title>プロンプト共有 - トップ</title>
        <link rel="icon" type="image/webp" href="/static/favicon.webp" />
        <link rel="icon" type="image/png" href="/static/favicon.png" />
        <link rel="dns-prefetch" href="https://cdn.jsdelivr.net" />
        <link rel="preconnect" href="https://cdn.jsdelivr.net" crossOrigin="anonymous" />
      </Head>

      <div className="prompt-share-page">
        <PromptSharePageContent />
      </div>
    </>
  );
}
