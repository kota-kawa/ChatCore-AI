// components/chat/popup_menu.ts (chat-specific)
import { getStoredThemePreference, setThemePreference, resolveTheme } from "../../core/theme";

const chatTemplate = document.createElement("template");
chatTemplate.innerHTML = `
  <style>
    :host {
      display: contents;
      --cc-fab-shadow: none;
      --cc-fab-hover-shadow: none;
      --cc-fab-hover-transform: scale(1.1);
      --cc-fab-hover-filter: brightness(1.06) saturate(1.1);
      --cc-fab-menu-shadow: none;
      --cc-fab-menu-bg: linear-gradient(135deg, #1a73e8, #19c37d, #d97706);
      --cc-fab-share-bg: linear-gradient(135deg, #1a73e8, #4a9bf5);
      --cc-fab-star-bg: linear-gradient(135deg, #19c37d, #0fa86a);
      --cc-fab-comment-bg: linear-gradient(135deg, #d97706, #f59e0b);
      --cc-fab-theme-bg: linear-gradient(135deg, #6b7280, #374151);
      --cc-fab-sheen: radial-gradient(circle at 28% 28%, rgba(255, 255, 255, 0.34), transparent 34%);
      --cc-fab-edge-highlight: inset 0 1px 0 rgba(255, 255, 255, 0.26);
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

    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }

    input[type="checkbox"] {
      display: none;
    }

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
    .btn--theme:hover {
      box-shadow:
        0 0 0 5px rgba(107, 114, 128, 0.20),
        0 6px 20px rgba(0, 0, 0, 0.16);
    }
    .btn svg {
      width: 24px;
      height: 24px;
      fill: #fff;
      transition: transform 0.3s ease;
    }

    .actions-menu {
      position: fixed;
      bottom: 40px;
      right: 40px;
      width: 60px;
      height: 60px;
      animation: popIn 0.6s ease;
      z-index: var(--z-floating-action-menu, 60);
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

    .btn--share {
      background: var(--cc-fab-share-bg);
    }
    .btn--star {
      background: var(--cc-fab-star-bg);
    }
    .btn--comment {
      background: var(--cc-fab-comment-bg);
    }
    .btn--theme {
      background: var(--cc-fab-theme-bg);
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
    .actions-menu .btn--theme   { transition-delay: 0s; }
    .actions-menu .btn--comment { transition-delay: 0.05s; }
    .actions-menu .btn--star    { transition-delay: 0.1s; }
    .actions-menu .btn--share   { transition-delay: 0.15s; }

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

    #chatActionMenuButton:checked + .actions-menu > .btn {
      opacity: 1;
      transform: scale(1) rotate(360deg);
      transition:
        top      0.52s cubic-bezier(0.34, 1.56, 0.64, 1),
        left     0.52s cubic-bezier(0.4, 0, 0.34, 1.56),
        opacity  0.4s  ease,
        transform 0.52s cubic-bezier(0.34, 1.56, 0.64, 1);
    }
    /* 開くとき順順カスケード: share→star→comment→theme */
    #chatActionMenuButton:checked + .actions-menu > .btn--share   { transition-delay: 0s; }
    #chatActionMenuButton:checked + .actions-menu > .btn--star    { transition-delay: 0.05s; }
    #chatActionMenuButton:checked + .actions-menu > .btn--comment { transition-delay: 0.1s; }
    #chatActionMenuButton:checked + .actions-menu > .btn--theme   { transition-delay: 0.15s; }

    /* 展開位置 */
    #chatActionMenuButton:checked + .actions-menu > .btn--share {
      top: -100px;
      left: 0px;
    }
    #chatActionMenuButton:checked + .actions-menu > .btn--star {
      top: -85px;
      left: -60px;
    }
    #chatActionMenuButton:checked + .actions-menu > .btn--comment {
      top: -45px;
      left: -95px;
    }
    #chatActionMenuButton:checked + .actions-menu > .btn--theme {
      top: 15px;
      left: -100px;
    }

    #chatActionMenuButton:checked + .actions-menu .btn--menu:after {
      transform: translate(-50%, -50%) rotate(45deg);
    }
    #chatActionMenuButton:checked + .actions-menu .btn--menu:before {
      transform: translate(-50%, -50%) rotate(-45deg);
    }
    #chatActionMenuButton:checked + .actions-menu .btn--menu span {
      transform: translate(-50%, -50%) scale(0);
    }

    .btn--share:hover svg { transform: rotate(-20deg) scale(1.2); }
    .btn--star:hover svg  { transform: rotate(20deg)  scale(1.2); }
    .btn--comment:hover svg { transform: rotate(-20deg) scale(1.2); }
    .btn--theme:hover svg { transform: rotate(20deg) scale(1.2); }

    @keyframes menuBtnWiggle {
      0%   { transform: scale(1.08) rotate(0deg); }
      45%  { transform: scale(1.08) rotate(-20deg); }
      100% { transform: scale(1.08) rotate(0deg); }
    }

    #chatActionMenuButton:not(:checked) + .actions-menu .btn--menu:hover {
      animation: menuBtnWiggle 0.45s cubic-bezier(0.34, 1.56, 0.64, 1) forwards;
    }

    @media (max-width: 768px) {
      .actions-menu {
        /* 固定inputの上に配置 (input ~56px + safe-area + 余白) */
        bottom: calc(70px + env(safe-area-inset-bottom, 0px));
        right: 12px;
        width: 48px;
        height: 48px;
      }
      .actions-menu .btn--menu {
        width: 48px !important;
        height: 48px !important;
      }
      .actions-menu .btn:not(.btn--menu) {
        width: 40px;
        height: 40px;
      }
      .btn svg {
        width: 20px;
        height: 20px;
      }
      /* 展開位置調整 */
      #chatActionMenuButton:checked + .actions-menu > .btn--share {
        top: -85px;
        left: 0px;
      }
      #chatActionMenuButton:checked + .actions-menu > .btn--star {
        top: -72px;
        left: -52px;
      }
      #chatActionMenuButton:checked + .actions-menu > .btn--comment {
        top: -38px;
        left: -80px;
      }
      #chatActionMenuButton:checked + .actions-menu > .btn--theme {
        top: 12px;
        left: -85px;
      }
    }

    @media (max-width: 480px) {
      .actions-menu {
        bottom: calc(65px + env(safe-area-inset-bottom, 0px));
        right: 10px;
        width: 44px;
        height: 44px;
      }
      .actions-menu .btn--menu {
        width: 44px !important;
        height: 44px !important;
      }
      .actions-menu .btn:not(.btn--menu) {
        width: 36px;
        height: 36px;
      }
      .btn svg {
        width: 18px;
        height: 18px;
      }
      /* 展開位置調整 */
      #chatActionMenuButton:checked + .actions-menu > .btn--share {
        top: -75px;
        left: 0px;
      }
      #chatActionMenuButton:checked + .actions-menu > .btn--star {
        top: -62px;
        left: -45px;
      }
      #chatActionMenuButton:checked + .actions-menu > .btn--comment {
        top: -32px;
        left: -70px;
      }
      #chatActionMenuButton:checked + .actions-menu > .btn--theme {
        top: 10px;
        left: -75px;
      }
    }
  </style>

  <input type="checkbox" id="chatActionMenuButton" />
  <div class="actions-menu">
    <button class="btn btn--share" onclick="location.href='/prompt_share'" data-tooltip="プロンプト共有へ移動" data-tooltip-placement="left">
      <svg viewBox="0 0 24 24">
        <path d="M18 16.08c-.76 0-1.44.3-1.96.77L8.91 12.7a3.048 3.048 0 0 0 0-1.39l7.13-4.17A3 3 0 1 0 14 5a3 3 0 0 0 .05.52l-7.14 4.18a3 3 0 1 0 0 4.6l7.14 4.18c-.03.17-.05.34-.05.52a3 3 0 1 0 3-2.92Z" />
      </svg>
    </button>
    <button class="btn btn--star" onclick="location.href='/'" data-tooltip="チャット設定へ戻る" data-tooltip-placement="left">
      <svg viewBox="0 0 24 24">
        <path d="M12,17.27L18.18,21L16.54,13.97 L22,9.24L14.81,8.62L12,2 L9.19,8.62L2,9.24L7.45,13.97 L5.82,21L12,17.27Z" />
      </svg>
    </button>
    <button class="btn btn--comment" onclick="location.href='/memo'" data-tooltip="メモ画面へ移動" data-tooltip-placement="left">
      <svg viewBox="0 0 24 24">
        <path d="M19 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h9l7-7V5a2 2 0 0 0-2-2Zm-5 14v-5h5l-5 5Z" />
      </svg>
    </button>
    <button id="themeToggleButton" class="btn btn--theme" data-tooltip="テーマを切り替え" data-tooltip-placement="left">
      <!-- Sun icon -->
      <svg id="themeIconSun" viewBox="0 0 24 24" style="display: none;">
        <path d="M12 7c-2.76 0-5 2.24-5 5s2.24 5 5 5 5-2.24 5-5-2.24-5-5-5ZM2 13h2c.55 0 1-.45 1-1s-.45-1-1-1H2c-.55 0-1 .45-1 1s.45 1 1 1Zm18 0h2c.55 0 1-.45 1-1s-.45-1-1-1h-2c-.55 0-1 .45-1 1s.45 1 1 1ZM11 2v2c0 .55.45 1 1 1s1-.45 1-1V2c0-.55-.45-1-1-1s-1 .45-1 1Zm0 18v2c0 .55.45 1 1 1s1-.45 1-1v-2c0-.55-.45-1-1-1s-1 .45-1 1ZM5.99 4.58a.996.996 0 0 0-1.41 0 .996.996 0 0 0 0 1.41l1.06 1.06c.39.39 1.03.39 1.41 0s.39-1.03 0-1.41L5.99 4.58Zm12.37 12.37a.996.996 0 0 0-1.41 0 .996.996 0 0 0 0 1.41l1.06 1.06c.39.39 1.03.39 1.41 0s.39-1.03 0-1.41l-1.06-1.06Zm1.06-12.37a.996.996 0 0 0-1.41 0l-1.06 1.06a.996.996 0 1 0 1.41 1.41l1.06-1.06a.996.996 0 0 0 0-1.41ZM7.05 18.36a.996.996 0 0 0-1.41 0l-1.06 1.06a.996.996 0 1 0 1.41 1.41l1.06-1.06a.996.996 0 0 0 0-1.41Z"/>
      </svg>
      <!-- Moon icon -->
      <svg id="themeIconMoon" viewBox="0 0 24 24" style="display: none;">
        <path d="M12 3a9 9 0 1 0 9 9c0-.46-.04-.92-.1-1.36a5.389 5.389 0 0 1-4.4 2.26 5.403 5.403 0 0 1-3.14-9.8c-.44-.06-.9-.1-1.36-.1Z"/>
      </svg>
    </button>
    <label for="chatActionMenuButton" class="btn btn--menu"><span></span></label>
  </div>
`;

class ChatActionMenu extends HTMLElement {
  private toggle: HTMLInputElement | null;
  private themeBtn: HTMLButtonElement | null;
  private sunIcon: SVGElement | null;
  private moonIcon: SVGElement | null;

  constructor() {
    super();
    const shadow = this.attachShadow({ mode: "open" });
    shadow.appendChild(chatTemplate.content.cloneNode(true));

    this.toggle = shadow.querySelector("#chatActionMenuButton") as HTMLInputElement | null;
    this.themeBtn = shadow.querySelector("#themeToggleButton") as HTMLButtonElement | null;
    this.sunIcon = shadow.querySelector("#themeIconSun") as SVGElement | null;
    this.moonIcon = shadow.querySelector("#themeIconMoon") as SVGElement | null;

    document.addEventListener("click", (event) => {
      if (this.toggle?.checked && !event.composedPath().includes(this)) {
        this.toggle.checked = false;
      }
    });

    // テーマ切り替えの初期化
    this.initThemeToggle();

    this.updateTextureContext();
    this.observeTextureContextChanges();
  }

  private initThemeToggle() {
    if (!this.themeBtn) return;

    const updateIcons = (theme: "light" | "dark") => {
      if (this.sunIcon && this.moonIcon) {
        if (theme === "dark") {
          this.sunIcon.style.display = "block";
          this.moonIcon.style.display = "none";
        } else {
          this.sunIcon.style.display = "none";
          this.moonIcon.style.display = "block";
        }
      }
    };

    // 初期状態の設定
    const currentPreference = getStoredThemePreference();
    const currentTheme = resolveTheme(currentPreference);
    updateIcons(currentTheme);

    this.themeBtn.addEventListener("click", () => {
      const pref = getStoredThemePreference();
      const nextTheme: "light" | "dark" = resolveTheme(pref) === "dark" ? "light" : "dark";
      setThemePreference(nextTheme);
      updateIcons(nextTheme);
      
      // 切り替え後、メニューを閉じる
      if (this.toggle) {
        this.toggle.checked = false;
      }
    });

    // 他の場所でのテーマ変更を監視
    window.addEventListener("storage", (e) => {
      if (e.key === "chatcore-theme") {
        const newTheme = resolveTheme(getStoredThemePreference());
        updateIcons(newTheme);
      }
    });
  }

  updateTextureContext() {
    const isChatPage = document.body.classList.contains("chat-page");
    this.toggleAttribute("data-chat-page", isChatPage);
  }

  observeTextureContextChanges() {
    const observer = new MutationObserver(() => {
      this.updateTextureContext();
    });
    observer.observe(document.body, { attributes: true, attributeFilter: ["class"] });
  }
}

if (!customElements.get("chat-action-menu")) {
  customElements.define("chat-action-menu", ChatActionMenu);
}

export {};
