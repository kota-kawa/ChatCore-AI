import Head from "next/head";
import { useEffect } from "react";

const bodyMarkup = `
  <action-menu></action-menu>

  <div id="auth-buttons" style="display:none; position:fixed; top:10px; right:10px; z-index: 2000;">
    <button id="login-btn" class="auth-btn">
      <i class="bi bi-person-circle"></i>
      <span>ログイン / 登録</span>
    </button>
  </div>

  <user-icon id="userIcon" style="display:none;"></user-icon>

  <header class="prompts-header" aria-labelledby="promptShareHeroTitle">
    <div class="prompts-header__inner">
      <p class="hero-kicker">Prompt Share</p>
      <h1 id="promptShareHeroTitle" class="hero-title">必要なプロンプトを、すぐ検索。</h1>
      <p class="hero-description">
        シンプルな検索で公開プロンプトを見つけて、そのまま保存・共有できます。
      </p>

      <div class="search-section" role="search" aria-label="プロンプト検索">
        <div class="search-box">
          <input type="text" id="searchInput" placeholder="キーワードでプロンプトを検索..." />
          <button
            id="searchButton"
            type="button"
            aria-label="検索を実行する"
            data-tooltip="入力したキーワードで検索"
            data-tooltip-placement="bottom"
          >
            <i class="bi bi-search"></i>
          </button>
        </div>
      </div>

      <div class="hero-actions">
        <button type="button" id="heroOpenPostModal" class="hero-action hero-action--primary">
          <i class="bi bi-plus-lg"></i>
          <span>プロンプトを投稿</span>
        </button>
      </div>
    </div>
  </header>

  <main>
    <section class="categories" aria-labelledby="categories-title">
      <div class="section-header section-header--compact">
        <h2 id="categories-title">カテゴリ</h2>
      </div>
      <div class="category-list">
        <button type="button" class="category-card active" data-category="all">
          <i class="bi bi-grid"></i>
          <span>全て</span>
        </button>
        <button type="button" class="category-card" data-category="恋愛">
          <i class="bi bi-heart-fill"></i>
          <span>恋愛</span>
        </button>
        <button type="button" class="category-card" data-category="勉強">
          <i class="bi bi-book"></i>
          <span>勉強</span>
        </button>
        <button type="button" class="category-card" data-category="趣味">
          <i class="bi bi-camera"></i>
          <span>趣味</span>
        </button>
        <button type="button" class="category-card" data-category="仕事">
          <i class="bi bi-briefcase"></i>
          <span>仕事</span>
        </button>
        <button type="button" class="category-card" data-category="その他">
          <i class="bi bi-stars"></i>
          <span>その他</span>
        </button>
        <button type="button" class="category-card" data-category="スポーツ">
          <i class="bi bi-trophy"></i>
          <span>スポーツ</span>
        </button>
        <button type="button" class="category-card" data-category="音楽">
          <i class="bi bi-music-note"></i>
          <span>音楽</span>
        </button>
        <button type="button" class="category-card" data-category="旅行">
          <i class="bi bi-geo-alt"></i>
          <span>旅行</span>
        </button>
        <button type="button" class="category-card" data-category="グルメ">
          <i class="bi bi-shop"></i>
          <span>グルメ</span>
        </button>
      </div>
    </section>

    <section id="prompt-feed-section" class="prompts-list" aria-labelledby="selected-category-title">
      <div class="section-header prompts-list-header section-header--compact">
        <h2 id="selected-category-title">全てのプロンプト</h2>
      </div>
      <div class="prompt-toolbar">
        <p id="promptCountMeta" class="prompt-count-meta">公開プロンプトを読み込み中...</p>
      </div>
      <div id="promptResults"></div>
      <div class="prompt-cards">
        <p class="prompt-loading-message">読み込み中...</p>
      </div>
    </section>
  </main>

  <!-- 投稿モーダル -->
  <div id="postModal" class="post-modal" role="dialog" aria-modal="true" aria-labelledby="postModalTitle" aria-hidden="true">
    <div class="post-modal-content post-modal-content--composer" tabindex="-1">
      <button type="button" class="close-btn" aria-label="投稿モーダルを閉じる">&times;</button>
      <div class="post-modal-scroll">
        <div class="composer-hero">
          <div class="composer-hero__copy">
            <p class="composer-hero__eyebrow">Prompt Share Composer</p>
            <h2 id="postModalTitle">新しいプロンプトを投稿</h2>
            <p class="post-modal-lead">AI 補助を使いながら、公開用の見やすさと使いやすさまでその場で仕上げます。</p>
          </div>
          <div class="composer-hero__chips" aria-hidden="true">
            <span>Searchable</span>
            <span>Polished</span>
            <span>Share Ready</span>
          </div>
        </div>
        <form class="post-form" id="postForm">
          <div class="form-group">
            <label>投稿タイプ</label>
            <div class="prompt-type-toggle" role="radiogroup" aria-label="投稿タイプを選択">
              <label class="prompt-type-option prompt-type-option--active">
                <input type="radio" name="prompt-type" value="text" checked />
                <span class="prompt-type-option__icon"><i class="bi bi-chat-square-text"></i></span>
                <span class="prompt-type-option__body">
                  <strong>通常プロンプト</strong>
                  <small>文章生成、要約、相談、分析など</small>
                </span>
              </label>
              <label class="prompt-type-option">
                <input type="radio" name="prompt-type" value="image" />
                <span class="prompt-type-option__icon"><i class="bi bi-image"></i></span>
                <span class="prompt-type-option__body">
                  <strong>画像生成プロンプト</strong>
                  <small>Midjourney、Stable Diffusion、Flux など向け</small>
                </span>
              </label>
            </div>
          </div>
          <div class="form-group">
            <label for="prompt-title">タイトル</label>
            <input type="text" id="prompt-title" placeholder="プロンプトのタイトルを入力" required />
          </div>
          <div class="form-group">
            <label for="prompt-category">カテゴリ</label>
            <select id="prompt-category" required>
              <option value="未選択" selected>未選択</option>
              <option value="恋愛">恋愛</option>
              <option value="勉強">勉強</option>
              <option value="趣味">趣味</option>
              <option value="仕事">仕事</option>
              <option value="その他">その他</option>
              <option value="スポーツ">スポーツ</option>
              <option value="音楽">音楽</option>
              <option value="旅行">旅行</option>
              <option value="グルメ">グルメ</option>
            </select>
          </div>
          <div class="form-group">
            <label for="prompt-content">プロンプト内容</label>
            <textarea id="prompt-content" rows="5" placeholder="具体的なプロンプト内容を入力" required></textarea>
          </div>
          <div id="sharedPromptAssistRoot"></div>
          <p id="promptPostStatus" class="composer-status" hidden></p>
          <div class="form-group">
            <label for="prompt-author">投稿者名</label>
            <input type="text" id="prompt-author" placeholder="ニックネームなど" value="アイデア職人" required />
          </div>
          <div class="form-group">
            <label for="prompt-ai-model">使用AIモデル（任意）</label>
            <select id="prompt-ai-model">
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
          <div id="imagePromptFields" class="image-prompt-fields" hidden>
            <div class="form-group">
              <label for="prompt-reference-image">作例画像（任意・1枚）</label>
              <label class="image-upload-field" for="prompt-reference-image">
                <input
                  type="file"
                  id="prompt-reference-image"
                  accept="image/png,image/jpeg,image/webp,image/gif"
                />
                <span class="image-upload-field__icon">
                  <i class="bi bi-cloud-arrow-up"></i>
                </span>
                <span class="image-upload-field__copy">
                  <strong>画像をアップロード</strong>
                  <small>PNG / JPG / WebP / GIF、5MBまで、1枚のみ</small>
                </span>
              </label>
              <div id="promptImagePreview" class="prompt-image-preview" hidden>
                <img id="promptImagePreviewImg" src="" alt="アップロード画像のプレビュー" />
                <div class="prompt-image-preview__meta">
                  <span id="promptImagePreviewName"></span>
                  <button type="button" id="promptImageClearButton" class="prompt-image-clear-btn">
                    <i class="bi bi-x-lg"></i>
                    <span>画像を外す</span>
                  </button>
                </div>
              </div>
            </div>
          </div>
          <div class="form-group form-group--toggle">
            <label class="composer-toggle" for="guardrail-checkbox">
              <input type="checkbox" id="guardrail-checkbox">
              <span class="composer-toggle__copy">
                <strong>入出力例を追加する</strong>
                <small>保存・再利用しやすい投稿にするため、プロンプトの使い方を例で添えます。</small>
              </span>
            </label>
          </div>

          <div id="guardrail-fields" style="display: none;">
            <div class="form-group">
              <label for="prompt-input-example">入力例（プロンプト内容とは別にしてください）</label>
              <textarea id="prompt-input-example" rows="3" placeholder="例: 夏休みの思い出をテーマにした短いエッセイを書いてください。"></textarea>
            </div>
            <div class="form-group">
              <label for="prompt-output-example">出力例</label>
              <textarea id="prompt-output-example" rows="3"
                placeholder="例: 夏休みのある日、私は家族と一緒に海辺へ出かけました。波の音と潮風に包まれながら、子供の頃の記憶がよみがえり、心が温かくなりました。その日は一生忘れられない、宝物のような時間となりました。"></textarea>
            </div>
          </div>

          <button type="submit" class="submit-btn">
            <i class="bi bi-upload"></i> 投稿する
          </button>
        </form>
      </div>
    </div>
  </div>

  <!-- プロンプト詳細モーダル -->
  <div id="promptDetailModal" class="post-modal" role="dialog" aria-modal="true" aria-labelledby="modalPromptTitle" aria-hidden="true">
    <div class="post-modal-content" tabindex="-1">
      <button type="button" class="close-btn" id="closePromptDetailModal" aria-label="詳細モーダルを閉じる">&times;</button>
      <h2 id="modalPromptTitle">プロンプト詳細</h2>
      <div class="modal-content-body">
        <div class="form-group">
          <label><strong>タイプ:</strong></label>
          <p id="modalPromptType"></p>
        </div>
        <div id="modalReferenceImageGroup" class="form-group" style="display: none;">
          <label><strong>作例画像:</strong></label>
          <div class="modal-reference-image">
            <img id="modalReferenceImage" src="" alt="作例画像" />
          </div>
        </div>
        <div class="form-group">
          <label><strong>カテゴリ:</strong></label>
          <p id="modalPromptCategory"></p>
        </div>
        <div class="form-group">
          <label><strong>内容:</strong></label>
          <p id="modalPromptContent"></p>
        </div>
        <div class="form-group">
          <label><strong>投稿者:</strong></label>
          <p id="modalPromptAuthor"></p>
        </div>
        <div id="modalAiModelGroup" class="form-group" style="display: none;">
          <label><strong>使用AIモデル:</strong></label>
          <p id="modalAiModel"></p>
        </div>
        <div id="modalInputExamplesGroup" class="form-group" style="display: none;">
          <label><strong>入力例:</strong></label>
          <p id="modalInputExamples"></p>
        </div>
        <div id="modalOutputExamplesGroup" class="form-group" style="display: none;">
          <label><strong>出力例:</strong></label>
          <p id="modalOutputExamples"></p>
        </div>
      </div>
    </div>
  </div>

  <div id="promptShareModal" class="post-modal prompt-share-modal" role="dialog" aria-modal="true" aria-labelledby="promptShareModalTitle" aria-hidden="true">
    <div class="post-modal-content prompt-share-dialog" tabindex="-1">
      <button type="button" class="close-btn" id="closePromptShareModal" aria-label="共有モーダルを閉じる">&times;</button>
      <h2 id="promptShareModalTitle">プロンプトを共有</h2>
      <p class="prompt-share-dialog__lead">このプロンプト専用のURLをコピーしたり、そのまま共有できます。</p>
      <div class="prompt-share-dialog__row">
        <input type="text" id="prompt-share-link-input" readonly placeholder="共有リンクを準備しています" />
      </div>
      <p id="prompt-share-status" class="prompt-share-dialog__status">共有するプロンプトを選択してください。</p>
      <div class="prompt-share-dialog__actions">
        <button type="button" id="prompt-share-create-btn" class="submit-btn">リンクを表示</button>
        <button type="button" id="prompt-share-copy-btn" class="submit-btn">リンクをコピー</button>
        <button type="button" id="prompt-share-web-btn" class="submit-btn">端末で共有</button>
      </div>
      <div class="prompt-share-dialog__sns">
        <a id="prompt-share-sns-x" target="_blank" rel="noopener noreferrer" href="#">
          <i class="bi bi-twitter"></i>
          <span>X</span>
        </a>
        <a id="prompt-share-sns-line" target="_blank" rel="noopener noreferrer" href="#">
          <i class="bi bi-chat-dots"></i>
          <span>LINE</span>
        </a>
        <a id="prompt-share-sns-facebook" target="_blank" rel="noopener noreferrer" href="#">
          <i class="bi bi-facebook"></i>
          <span>Facebook</span>
        </a>
      </div>
    </div>
  </div>

  <!-- 新規投稿ボタン -->
  <button
    id="openPostModal"
    class="new-prompt-btn"
    aria-label="新しいプロンプトを投稿"
    data-tooltip="新しいプロンプトを投稿"
    data-tooltip-placement="left"
  >
    <i class="bi bi-plus-lg"></i>
  </button>

  <!-- メインのJavaScript -->
`;

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
        <link
          rel="stylesheet"
          href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.5/font/bootstrap-icons.css"
        />
      </Head>
      <div className="prompt-share-page" dangerouslySetInnerHTML={{ __html: bodyMarkup }} />
    </>
  );
}
