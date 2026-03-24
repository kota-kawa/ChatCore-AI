// components/user_icon.ts
// ────────────────────────────────────────────────
// 右上ユーザーアイコン  +  ドロップダウンメニュー
//  - /api/user/profile で avatar_url / username を取得
//  - 取得失敗時はデフォルト画像・空文字にフォールバック
// ────────────────────────────────────────────────

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
    }
    .btn {
      background: transparent;
      border: none;
      cursor: pointer;
      padding: .5rem;
      border-radius: 50%;
      transition: background-color .15s;
      display: inline-flex;
      align-items: center;
      justify-content: center;
    }
    :host([data-chat-page="true"]) .btn {
      background:
        var(--cc-user-btn-sheen),
        linear-gradient(135deg, rgba(255, 255, 255, 0.98) 0%, rgba(239, 247, 242, 0.98) 100%);
      transition: transform .2s ease, filter .2s ease, box-shadow .2s ease;
      box-shadow:
        0 14px 24px rgba(15, 23, 42, 0.12),
        var(--cc-user-btn-edge-highlight);
    }
    .btn:hover {
      background: rgba(0,0,0,.06);
    }
    :host([data-chat-page="true"]) .btn:hover {
      background:
        var(--cc-user-btn-sheen),
        linear-gradient(135deg, rgba(255, 255, 255, 0.98) 0%, rgba(239, 247, 242, 0.98) 100%);
      transform: translateY(-1px);
      filter: saturate(1.06);
      box-shadow:
        0 18px 30px rgba(15, 23, 42, 0.16),
        var(--cc-user-btn-edge-highlight);
    }
    .avatar {
      width: 2.2rem;
      height: 2.2rem;
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
    <img class="avatar" src="/static/user-icon.png" alt="ユーザーアイコン">
  </button>

  <div class="dropdown">
    <a class="item" href="/settings">⚙️ 設定</a>
    <a class="item" href="/logout">🚪 ログアウト</a>
  </div>
`;

async function postLogoutAndRedirect() {
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
    if (typeof window.loggedIn !== "undefined") {
      this._handleAuthStateInternal({ detail: { loggedIn: window.loggedIn } } as CustomEvent);
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
      if (!this._profileLoaded) {
        this.loadProfile();
      }
    } else {
      this._profileLoaded = false;
      this.dropdown.style.display = "none";
      this.avatarImg.src = "/static/user-icon.png";
      this.avatarImg.alt = "ユーザーアイコン";
    }
  }

  async loadProfile() {
    try {
      const res = await fetch("/api/user/profile", { credentials: "same-origin" });
      if (res.status === 401) {
        // 未ログイン時は静かに何もしない
        this._profileLoaded = false;
        return;
      }
      if (!res.ok) throw new Error(`status ${res.status}`);
      const data = await res.json();

      const avatar = data.avatar_url || "/static/user-icon.png";
      const name = typeof data.username === "string" ? data.username.trim() : "";

      this.avatarImg.src = avatar;
      // alt 属性にもセット
      this.avatarImg.alt = name ? `${name}のアイコン` : "ユーザーアイコン";
      this._profileLoaded = true;
    } catch (err) {
      console.warn("user_icon: profile load failed", err);
      this._profileLoaded = false;
    }
  }
}

if (!customElements.get("user-icon")) {
  customElements.define("user-icon", UserIcon);
}

export {};
