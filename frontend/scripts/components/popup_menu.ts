// components/popup_menu.ts
import { getStoredThemePreference, setThemePreference, resolveTheme } from "../core/theme";

const template = document.createElement("template");
template.innerHTML = `
  <style>
    :host {
      --cc-fab-sheen: radial-gradient(circle at 28% 28%, rgba(255, 255, 255, 0.34), transparent 34%);
      --cc-fab-edge-highlight: inset 0 1px 0 rgba(255, 255, 255, 0.24);
      --cc-fab-shadow: none;
      --cc-fab-hover-shadow: none;
      --cc-fab-hover-transform: scale(1.08);
      --cc-fab-hover-filter: brightness(1.07) saturate(1.12);
      --cc-fab-menu-shadow: none;
      --cc-fab-menu-bg: var(--cc-fab-sheen), linear-gradient(135deg, #1a73e8, #19c37d, #d97706);
      --cc-fab-share-bg: var(--cc-fab-sheen), linear-gradient(135deg, #1a73e8, #4a9bf5);
      --cc-fab-star-bg: var(--cc-fab-sheen), linear-gradient(135deg, #19c37d, #0fa86a);
      --cc-fab-comment-bg: var(--cc-fab-sheen), linear-gradient(135deg, #d97706, #f59e0b);
    }


    :host([data-chat-page="true"]) {
      --cc-fab-shadow: none;
      --cc-fab-hover-shadow: none;
      --cc-fab-hover-transform: scale(1.08);
      --cc-fab-hover-filter: brightness(1.07) saturate(1.12);
      --cc-fab-menu-shadow: none;
      --cc-fab-menu-bg: var(--cc-fab-sheen), linear-gradient(135deg, #1a73e8, #19c37d, #d97706);
      --cc-fab-share-bg: var(--cc-fab-sheen), linear-gradient(135deg, #1a73e8, #4a9bf5);
      --cc-fab-star-bg: var(--cc-fab-sheen), linear-gradient(135deg, #19c37d, #0fa86a);
      --cc-fab-comment-bg: var(--cc-fab-sheen), linear-gradient(135deg, #d97706, #f59e0b);
    }

    /* ============
       Reset / Base
       ============ */
    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }

    /* ============
       Hidden Checkbox
       ============ */
    input[type="checkbox"] {
      display: none;
    }

    /* ============
       Common Button Styles
       ============ */
    .btn {
      border: none;
      border-radius: 50%;
      width: 50px;
      height: 50px;
      cursor: pointer;
      display: flex;
      justify-content: center;
      align-items: center;
      transition: transform 0.22s cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 0.22s ease, filter 0.22s ease;
      box-shadow: var(--cc-fab-shadow);
      position: relative;
    }
    .btn:hover {
      transform: var(--cc-fab-hover-transform);
      filter: var(--cc-fab-hover-filter);
      box-shadow: var(--cc-fab-hover-shadow);
    }
    .btn--menu:hover {
      box-shadow:
        0 0 0 5px rgba(25, 195, 125, 0.18),
        0 6px 20px rgba(0, 0, 0, 0.18);
    }
    .btn--share:hover {
      box-shadow:
        0 0 0 5px rgba(26, 115, 232, 0.20),
        0 6px 20px rgba(0, 0, 0, 0.16);
    }
    .btn--star:hover {
      box-shadow:
        0 0 0 5px rgba(25, 195, 125, 0.20),
        0 6px 20px rgba(0, 0, 0, 0.16);
    }
    .btn--comment:hover {
      box-shadow:
        0 0 0 5px rgba(217, 119, 6, 0.20),
        0 6px 20px rgba(0, 0, 0, 0.16);
    }
    .btn svg {
      width: 24px;
      height: 24px;
      fill: #fff;
      transition: transform 0.3s ease;
    }

    /* ============
       Action Menu Wrapper
       ============ */
    .actions-menu {
      position: fixed;
      bottom: 40px;
      right: 40px;
      width: 60px;
      height: 60px;
      animation: popIn 0.6s ease;
      z-index: var(--z-floating-action-menu, 60);
    }

    :host([data-context="chat"]) .actions-menu {
      display: none;
    }

    :host([data-context="non-chat"]) .actions-menu {
      bottom: 40px; /* Align with floating prompt button on desktop */
    }

    @keyframes popIn {
      0% {
        transform: scale(0.5) rotate(0deg);
        opacity: 0;
      }
      80% {
        transform: scale(1.05) rotate(360deg);
        opacity: 1;
      }
      100% {
        transform: scale(1) rotate(360deg);
        opacity: 1;
      }
    }

    /* ============
       Menu Button (Large)
       ============ */
    .btn--menu {
      width: 60px;
      height: 60px;
      background: var(--cc-fab-menu-bg);
      z-index: 1;
    }
    .btn--menu:after,
    .btn--menu:before,
    .btn--menu span {
      content: "";
      position: absolute;
      width: 25px;
      height: 3px;
      background: #fff;
      transition: transform 0.32s cubic-bezier(0.34, 1.56, 0.64, 1);
    }
    .btn--menu span {
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%);
    }
    .btn--menu:after {
      top: 50%;
      left: 50%;
      transform: translate(-50%, calc(-50% - 8px));
    }
    .btn--menu:before {
      top: 50%;
      left: 50%;
      transform: translate(-50%, calc(-50% + 8px));
    }

    /* ============
       Action Buttons
       ============ */
    .btn--share {
      background: var(--cc-fab-share-bg);
    }
    .btn--star {
      background: var(--cc-fab-star-bg);
    }
    .btn--comment {
      background: var(--cc-fab-comment-bg);
    }

    /* ============
       ボタンの配置
       ============ */
    .actions-menu .btn {
      position: absolute;
      top: 8px;
      left: 8px;
      opacity: 0;
      transform: scale(0) rotate(0deg);
      /* 閉じるアニメーション */
      transition:
        top      0.38s cubic-bezier(0.4, 0, 0.65, 1),
        left     0.38s cubic-bezier(0.4, 0, 0.65, 1),
        opacity  0.28s ease,
        transform 0.4s  cubic-bezier(0.4, 0, 0.65, 1);
    }
    /* 閉じるとき逆順カスケード */
    .actions-menu .btn--comment { transition-delay: 0s; }
    .actions-menu .btn--star    { transition-delay: 0.05s; }
    .actions-menu .btn--share   { transition-delay: 0.1s; }

    .actions-menu .btn--menu {
      position: absolute;
      top: 0;
      left: 0;
      width: 60px;
      height: 60px;
      opacity: 1;
      box-shadow: var(--cc-fab-menu-shadow);
      transform: none;
    }

    /* ============
       チェックが入ったら各アイコンが展開
       ============ */
    #actionMenuButton:checked + .actions-menu > .btn {
      opacity: 1;
      transform: scale(1) rotate(360deg);
      transition:
        top      0.52s cubic-bezier(0.34, 1.56, 0.64, 1),
        left     0.52s cubic-bezier(0.34, 1.56, 0.64, 1),
        opacity  0.4s  ease,
        transform 0.52s cubic-bezier(0.34, 1.56, 0.64, 1);
    }
    /* 開くとき順順カスケード: share→star→comment */
    #actionMenuButton:checked + .actions-menu > .btn--share   { transition-delay: 0s; }
    #actionMenuButton:checked + .actions-menu > .btn--star    { transition-delay: 0.05s; }
    #actionMenuButton:checked + .actions-menu > .btn--comment { transition-delay: 0.1s; }

    /* 展開位置 */
    #actionMenuButton:checked + .actions-menu > .btn--share {
      top: -100px;
      left: 0px;
    }
    #actionMenuButton:checked + .actions-menu > .btn--star {
      top: -85px;
      left: -60px;
    }
    #actionMenuButton:checked + .actions-menu > .btn--comment {
      top: -15px;
      left: -100px;
    }

    /* ============
       ハンバーガー変形
       ============ */
    #actionMenuButton:checked + .actions-menu .btn--menu:after {
      transform: translate(-50%, -50%) rotate(45deg);
    }
    #actionMenuButton:checked + .actions-menu .btn--menu:before {
      transform: translate(-50%, -50%) rotate(-45deg);
    }
    #actionMenuButton:checked + .actions-menu .btn--menu span {
      transform: translate(-50%, -50%) scale(0);
    }

    /* ============
       ホバーアニメーション
       ============ */
    .btn--share:hover svg { transform: rotate(-20deg) scale(1.2); }
    .btn--star:hover svg  { transform: rotate(20deg)  scale(1.2); }
    .btn--comment:hover svg { transform: rotate(-20deg) scale(1.2); }

    @keyframes menuBtnWiggle {
      0%   { transform: scale(1.08) rotate(0deg); }
      45%  { transform: scale(1.08) rotate(-20deg); }
      100% { transform: scale(1.08) rotate(0deg); }
    }

    #actionMenuButton:not(:checked) + .actions-menu .btn--menu:hover {
      animation: menuBtnWiggle 0.45s cubic-bezier(0.34, 1.56, 0.64, 1) forwards;
    }
  
  
  /* スマホ表示時の調整（画面幅768px以下） - プロンプト投稿ボタンと同じサイズに */
    @media (max-width: 768px) {
      /* メニュー全体の位置とサイズ */
      .actions-menu {
        right: 20px;    /* プロンプト投稿ボタンの位置に合わせて調整 */
        width: 56px;    /* プロンプト投稿ボタンと同じサイズに */
        height: 56px;   /* プロンプト投稿ボタンと同じサイズに */
      }

      :host([data-context="chat"]) .actions-menu {
        bottom: 100px;  /* チャット入力フォームから十分離して配置 */
      }

      :host([data-context="non-chat"]) .actions-menu {
        bottom: 20px;   /* プロンプト投稿ボタンと同じ高さに配置 */
      }
      /* ハンバーガーボタンをプロンプト投稿ボタンと完全に同じサイズに */
      .actions-menu .btn--menu {
        width: 56px !important;
        height: 56px !important;
      }
      /* 他のボタンのサイズ */
      .actions-menu .btn:not(.btn--menu) {
        width: 45px;
        height: 45px;
      }
      /* アイコンサイズ調整 */
      .btn svg {
        width: 20px;
        height: 20px;
      }

      /* 展開位置調整 */
      #actionMenuButton:checked + .actions-menu > .btn--share {
        top: -85px;
        left: 0px;
      }
      #actionMenuButton:checked + .actions-menu > .btn--star {
        top: -72px;
        left: -52px;
      }
      #actionMenuButton:checked + .actions-menu > .btn--comment {
        top: -5px;
        left: -85px;
      }
    }

    /* 非常に小さな画面での調整（画面幅480px以下） - プロンプト投稿ボタンと完全に同じサイズに */
    @media (max-width: 480px) {
      /* メニュー全体のサイズをプロンプト投稿ボタンに完全に合わせて調整 */
      .actions-menu {
        bottom: 90px;   /* 入力フォームから十分離して配置 */
        right: 15px;    /* プロンプト投稿ボタンの位置に合わせて調整 */
        width: 50px;    /* プロンプト投稿ボタンと同じサイズに */
        height: 50px;   /* プロンプト投稿ボタンと同じサイズに */
      }
      /* ハンバーガーボタンをプロンプト投稿ボタンと完全に同じサイズに */
      .actions-menu .btn--menu {
        width: 50px !important;
        height: 50px !important;
      }
      /* 他のボタンのサイズをより小さく */
      .actions-menu .btn:not(.btn--menu) {
        width: 40px;
        height: 40px;
      }
      /* アイコンもさらに縮小 */
      .btn svg {
        width: 18px;
        height: 18px;
      }

      :host([data-context="chat"]) .actions-menu {
        bottom: 90px;   /* チャット入力フォームから十分離して配置 */
      }

      :host([data-context="non-chat"]) .actions-menu {
        bottom: 15px;   /* プロンプト投稿ボタンと同じ高さに配置 */
      }

      /* 展開位置調整 */
      #actionMenuButton:checked + .actions-menu > .btn--share {
        top: -75px;
        left: 0px;
      }
      #actionMenuButton:checked + .actions-menu > .btn--star {
        top: -62px;
        left: -45px;
      }
      #actionMenuButton:checked + .actions-menu > .btn--comment {
        top: -5px;
        left: -75px;
      }
    }

    </style>

  <!-- チェックボックス（メニュー開閉用） -->
  <input type="checkbox" id="actionMenuButton" />

  <!-- アクションメニュー本体 -->
  <div class="actions-menu">
    <button class="btn btn--share" onclick="location.href='/prompt_share'" data-tooltip="プロンプト共有へ移動" data-tooltip-placement="left">
      <svg viewBox="0 0 24 24">
        <path d="M18 16.08c-.76 0-1.44.3-1.96.77L8.91 12.7a3.048 3.048 0 0 0 0-1.39l7.13-4.17A3 3 0 1 0 14 5a3 3 0 0 0 .05.52l-7.14 4.18a3 3 0 1 0 0 4.6l7.14 4.18c-.03.17-.05.34-.05.52a3 3 0 1 0 3-2.92Z" />
      </svg>
    </button>
    <button class="btn btn--star" onclick="location.href='/'" data-tooltip="チャット画面へ移動" data-tooltip-placement="left">
      <svg viewBox="0 0 24 24">
        <path d="M12,17.27L18.18,21L16.54,13.97 L22,9.24L14.81,8.62L12,2 L9.19,8.62L2,9.24L7.45,13.97 L5.82,21L12,17.27Z" />
      </svg>
    </button>
    <button class="btn btn--comment" onclick="location.href='/memo'" data-tooltip="メモ画面へ移動" data-tooltip-placement="left">
      <svg viewBox="0 0 24 24">
        <path d="M19 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h9l7-7V5a2 2 0 0 0-2-2Zm-5 14v-5h5l-5 5Z" />
      </svg>
    </button>
    <label for="actionMenuButton" class="btn btn--menu"><span></span></label>
  </div>
`;

class ActionMenu extends HTMLElement {
  private toggle: HTMLInputElement | null;

  constructor() {
    super();
    const shadow = this.attachShadow({ mode: "open" });
    shadow.appendChild(template.content.cloneNode(true));

    this.toggle = shadow.querySelector("#actionMenuButton") as HTMLInputElement | null;

    //  メニュー外クリックで自動クローズ
    if (this.toggle) {
      document.addEventListener("click", (e) => {
        // メニューが開いていて，クリック先がこのコンポーネント外なら閉じる
        if (this.toggle?.checked && !e.composedPath().includes(this)) {
          this.toggle.checked = false;
        }
      });
    }

    // チャット画面かどうかを検出して適切なサイズを適用
    this.updateMenuSize();
    // 画面の変化を監視
    this.observeScreenChanges();
  }

  updateMenuSize() {
    const chatContainer = document.getElementById("chat-container") as HTMLElement | null;
    const pageViewState = chatContainer?.getAttribute("data-view");
    const isInChatMode = pageViewState === "chat" || pageViewState === "launching";
    const isChatPage = document.body.classList.contains("chat-page");

    // CSSカスタムプロパティでコンテキストを設定
    if (isInChatMode) {
      this.setAttribute("data-context", "chat");
    } else {
      this.setAttribute("data-context", "non-chat");
    }

    this.toggleAttribute("data-chat-page", isChatPage);
  }

  observeScreenChanges() {
    const chatContainer = document.getElementById("chat-container");
    const observer = new MutationObserver(() => {
      this.updateMenuSize();
    });

    // MutationObserverで画面切り替え属性の変化を監視
    if (chatContainer) {
      observer.observe(chatContainer, {
        attributes: true,
        attributeFilter: ["data-view"]
      });
    }

    // 定期的にもチェック（念のため）
    setInterval(() => {
      this.updateMenuSize();
    }, 1000);
  }
}

if (!customElements.get("action-menu")) {
  customElements.define("action-menu", ActionMenu);
}

export {};
