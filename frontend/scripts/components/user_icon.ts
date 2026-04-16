// components/user_icon.ts
// ────────────────────────────────────────────────
import { getLoggedInState, hasLoggedInState } from "../core/app_state";
// 右上ユーザーアイコン  +  ドロップダウンメニュー
//  - /api/user/profile で avatar_url / username を取得
//  - カスタム画像がある場合はデフォルト画像を先に出さない
// ────────────────────────────────────────────────

const DEFAULT_AVATAR_URL = "/static/user-icon.png";
const AVATAR_CACHE_KEY = "chatcore.userIcon.avatarUrl";
const USERNAME_CACHE_KEY = "chatcore.userIcon.username";

function normalizeText(value: unknown) {
  return typeof value === "string" ? value.trim() : "";
}

function hasCustomAvatar(value: unknown) {
  const avatarUrl = normalizeText(value);
  return avatarUrl !== "" && avatarUrl !== DEFAULT_AVATAR_URL;
}

function readCachedProfile() {
  try {
    const avatarUrl = normalizeText(sessionStorage.getItem(AVATAR_CACHE_KEY));
    if (!hasCustomAvatar(avatarUrl)) {
      return null;
    }

    return {
      avatarUrl,
      username: normalizeText(sessionStorage.getItem(USERNAME_CACHE_KEY))
    };
  } catch {
    return null;
  }
}

function writeCachedProfile(avatarUrl: string, username: string) {
  if (!hasCustomAvatar(avatarUrl)) {
    clearCachedProfile();
    return;
  }

  try {
    sessionStorage.setItem(AVATAR_CACHE_KEY, avatarUrl);
    if (username) {
      sessionStorage.setItem(USERNAME_CACHE_KEY, username);
    } else {
      sessionStorage.removeItem(USERNAME_CACHE_KEY);
    }
  } catch {
    // sessionStorage が使えなくても表示は継続する
  }
}

function clearCachedProfile() {
  try {
    sessionStorage.removeItem(AVATAR_CACHE_KEY);
    sessionStorage.removeItem(USERNAME_CACHE_KEY);
  } catch {
    // sessionStorage が使えなくても表示は継続する
  }
}

const tpl = document.createElement("template");
tpl.innerHTML = `
  <style>
    :host {
      position: fixed;
      top: 10px;
      right: 10px;
      z-index: 10000;
      font-family: inherit;
      user-select: none;
      --cc-user-btn-sheen: radial-gradient(circle at 28% 28%, rgba(255, 255, 255, 0.34), transparent 34%);
      --cc-user-btn-edge-highlight: inset 0 1px 0 rgba(255, 255, 255, 0.24);
      --cc-user-btn-base: #19c37d;
      --cc-user-btn-accent: #15a86b;
      --cc-user-btn-shadow-color: rgba(15, 122, 81, 0.22);
    }
    .btn {
      background: transparent;
      border: none;
      cursor: pointer;
      padding: .25rem;
      border-radius: 50%;
      transition: transform .2s ease, opacity .2s ease;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      box-shadow: none;
      opacity: 0;
      pointer-events: none;
    }
    :host([data-avatar-ready="true"]) .btn {
      opacity: 1;
      pointer-events: auto;
    }
    :host([data-chat-page="true"]) .btn {
      --cc-user-btn-base: rgba(255, 255, 255, 0.98);
      --cc-user-btn-accent: rgba(239, 247, 242, 0.98);
      --cc-user-btn-shadow-color: rgba(15, 23, 42, 0.12);
    }
    .btn:hover {
      transform: translateY(-1px);
    }
    .btn:active {
      transform: scale(0.97);
    }
    .avatar {
      width: 2.5rem;
      height: 2.5rem;
      border-radius: 50%;
      object-fit: cover;
      display: block;
    }
    /* ▼ dropdown */
    .dropdown {
      position: absolute;
      top: 3rem;
      right: 0;
      background: #fff;
      border: 1px solid #ddd;
      border-radius: 6px;
      box-shadow: 0 2px 8px rgba(0,0,0,.1);
      min-width: 160px;
      display: none;
      flex-direction: column;
      overflow: hidden;
      animation: fade .15s ease-out;
    }
    @keyframes fade { from { opacity: 0; transform: translateY(-5px);}
                      to   { opacity: 1; transform: translateY(0);} }
    .item {
      padding: .6rem 1rem;
      font-size: .9rem;
      text-decoration: none;
      color: #333;
      display: flex;
      align-items: center;
      gap: .5rem;
      cursor: pointer;
    }
    .item:hover { background: #f5f5f5; }
  </style>

  <button class="btn" aria-label="アカウントメニューを開く">
    <img class="avatar" alt="ユーザーアイコン" hidden>
  </button>

  <div class="dropdown">
    <a class="item" href="/settings">⚙️ 設定</a>
    <a class="item" href="/logout">🚪 ログアウト</a>
  </div>
`;

async function postLogoutAndRedirect() {
  clearCachedProfile();
  try {
    const response = await fetch("/logout", {
      method: "POST",
      credentials: "same-origin"
    });
    if (response.redirected && response.url) {
      window.location.href = response.url;
      return;
    }
  } catch (error) {
    console.warn("user_icon: logout request failed", error);
  }
  window.location.href = "/login";
}

class UserIcon extends HTMLElement {
  private btn: HTMLButtonElement;
  private dropdown: HTMLDivElement;
  private avatarImg: HTMLImageElement;
  private bodyClassObserver: MutationObserver | null = null;
  private _profileLoaded = false;
  private _profileRequest: Promise<void> | null = null;
  private _profileRequestVersion = 0;
  private _handleAuthState: (evt?: Event) => void;

  constructor() {
    super();
    const root = this.attachShadow({ mode: "open" });
    root.append(tpl.content.cloneNode(true));

    const btn = root.querySelector(".btn") as HTMLButtonElement | null;
    const dropdown = root.querySelector(".dropdown") as HTMLDivElement | null;
    const avatarImg = root.querySelector(".avatar") as HTMLImageElement | null;

    if (!btn || !dropdown || !avatarImg) {
      throw new Error("user-icon template is missing required elements");
    }

    this.btn = btn;
    this.dropdown = dropdown;
    this.avatarImg = avatarImg;
    this._handleAuthState = this._handleAuthStateInternal.bind(this);
    this.setAvatarPending();

    // ドロップダウン開閉
    this.btn.addEventListener("click", (e) => {
      e.stopPropagation();
      this.dropdown.style.display =
        this.dropdown.style.display === "flex" ? "none" : "flex";
    });
    // 外側クリックで閉じる
    document.addEventListener("click", () => {
      this.dropdown.style.display = "none";
    });
    const logoutAnchor = root.querySelector('a[href="/logout"]') as HTMLAnchorElement | null;
    logoutAnchor?.addEventListener("click", (event) => {
      event.preventDefault();
      this.dropdown.style.display = "none";
      void postLogoutAndRedirect();
    });

  }

  connectedCallback() {
    this.syncTextureContext();
    if (document.body) {
      this.bodyClassObserver = new MutationObserver(() => {
        this.syncTextureContext();
      });
      this.bodyClassObserver.observe(document.body, {
        attributes: true,
        attributeFilter: ["class"]
      });
    }
    document.addEventListener("authstatechange", this._handleAuthState);
    if (hasLoggedInState()) {
      this._handleAuthStateInternal({ detail: { loggedIn: getLoggedInState() } } as CustomEvent);
    }
  }

  disconnectedCallback() {
    if (this.bodyClassObserver) {
      this.bodyClassObserver.disconnect();
      this.bodyClassObserver = null;
    }
    document.removeEventListener("authstatechange", this._handleAuthState);
  }

  private syncTextureContext() {
    this.toggleAttribute("data-chat-page", document.body.classList.contains("chat-page"));
  }

  private _handleAuthStateInternal(evt?: Event) {
    const customEvent = evt as CustomEvent<{ loggedIn?: boolean }> | undefined;
    const loggedIn = Boolean(customEvent?.detail?.loggedIn);

    if (loggedIn) {
      if (!this._profileLoaded && !this.restoreCachedAvatar()) {
        this.setAvatarPending();
      }
      void this.loadProfile();
    } else {
      this._profileLoaded = false;
      this._profileRequestVersion += 1;
      this._profileRequest = null;
      this.dropdown.style.display = "none";
      clearCachedProfile();
      this.setAvatarPending();
    }
  }

  async loadProfile() {
    if (this._profileLoaded) {
      return;
    }
    if (this._profileRequest) {
      await this._profileRequest;
      return;
    }

    const requestVersion = ++this._profileRequestVersion;
    this._profileRequest = this.loadProfileInternal(requestVersion);

    try {
      await this._profileRequest;
    } finally {
      this._profileRequest = null;
    }
  }

  private async loadProfileInternal(requestVersion: number) {
    try {
      const res = await fetch("/api/user/profile", { credentials: "same-origin" });
      if (requestVersion !== this._profileRequestVersion) {
        return;
      }
      if (res.status === 401) {
        // 未ログイン時は静かに何もしない
        this._profileLoaded = false;
        clearCachedProfile();
        this.setAvatarPending();
        return;
      }
      if (!res.ok) throw new Error(`status ${res.status}`);
      const data = await res.json();
      if (requestVersion !== this._profileRequestVersion) {
        return;
      }

      const avatar = normalizeText(data.avatar_url);
      const name = normalizeText(data.username);

      if (hasCustomAvatar(avatar)) {
        writeCachedProfile(avatar, name);
        this.setAvatar(avatar, name);
      } else {
        clearCachedProfile();
        this.setAvatar(DEFAULT_AVATAR_URL, name);
      }
      this._profileLoaded = true;
    } catch (err) {
      if (requestVersion !== this._profileRequestVersion) {
        return;
      }
      console.warn("user_icon: profile load failed", err);
      this._profileLoaded = false;
    }
  }

  private restoreCachedAvatar() {
    const cachedProfile = readCachedProfile();
    if (!cachedProfile) {
      return false;
    }

    this.setAvatar(cachedProfile.avatarUrl, cachedProfile.username);
    return true;
  }

  private setAvatarPending() {
    this.removeAttribute("data-avatar-ready");
    this.avatarImg.hidden = true;
    this.avatarImg.removeAttribute("src");
    this.avatarImg.alt = "ユーザーアイコン";
  }

  private setAvatar(avatarUrl: string, username: string) {
    this.avatarImg.hidden = false;
    this.avatarImg.src = avatarUrl;
    this.avatarImg.alt = username ? `${username}のアイコン` : "ユーザーアイコン";
    this.setAttribute("data-avatar-ready", "true");
  }
}

if (!customElements.get("user-icon")) {
  customElements.define("user-icon", UserIcon);
}

export {};
