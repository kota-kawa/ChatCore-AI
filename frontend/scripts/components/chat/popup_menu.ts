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

    #chatActionMenuButton:checked + .actions-menu > .btn {
      opacity: 1;
      transform: scale(1) rotate(360deg);
      transition:
        top      0.52s cubic-bezier(0.34, 1.56, 0.64, 1),
        left     0.52s cubic-bezier(0.4, 0, 0.34, 1.56),
        opacity  0.4s  ease,
        transform 0.52s cubic-bezier(0.34, 1.56, 0.64, 1);
    }
    /* 開くとき順順カスケード: share→star→comment */
    #chatActionMenuButton:checked + .actions-menu > .btn--share   { transition-delay: 0s; }
    #chatActionMenuButton:checked + .actions-menu > .btn--star    { transition-delay: 0.05s; }
    #chatActionMenuButton:checked + .actions-menu > .btn--comment { transition-delay: 0.1s; }

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
      top: -15px;
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
        top: -5px;
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
        top: -5px;
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
    <label for="chatActionMenuButton" class="btn btn--menu"><span></span></label>
  </div>
`;

const CHAT_ACTION_MENU_OPEN_KEY = "chatActionMenu.isOpen";

class ChatActionMenu extends HTMLElement {
  private toggle: HTMLInputElement | null;

  constructor() {
    super();
    const shadow = this.attachShadow({ mode: "open" });
    shadow.appendChild(chatTemplate.content.cloneNode(true));

    this.toggle = shadow.querySelector("#chatActionMenuButton") as HTMLInputElement | null;

    if (this.toggle) {
      try {
        if (window.sessionStorage.getItem(CHAT_ACTION_MENU_OPEN_KEY) === "1") {
          this.toggle.checked = true;
        }
      } catch {
        // ignore sessionStorage failures
      }

      this.toggle.addEventListener("change", () => {
        try {
          window.sessionStorage.setItem(CHAT_ACTION_MENU_OPEN_KEY, this.toggle?.checked ? "1" : "0");
        } catch {
          // ignore sessionStorage failures
        }
      });
    }

    document.addEventListener("click", (event) => {
      if (this.toggle?.checked && !event.composedPath().includes(this)) {
        this.toggle.checked = false;
        try {
          window.sessionStorage.setItem(CHAT_ACTION_MENU_OPEN_KEY, "0");
        } catch {
          // ignore sessionStorage failures
        }
      }
    });

    this.updateTextureContext();
    this.observeTextureContextChanges();
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
