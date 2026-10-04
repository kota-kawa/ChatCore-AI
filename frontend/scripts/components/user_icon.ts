// components/user_icon.ts
// ────────────────────────────────────────────────
import { getLoggedInState, hasLoggedInState } from "../core/app_state";
import { resilientFetch } from "../core/resilient_fetch";
import { STORAGE_KEYS } from "../core/constants";
import {
  DEFAULT_AVATAR_URL,
  clearCachedUserIconProfile,
  readCachedUserIconProfile,
  writeCachedUserIconProfile
} from "../core/user_icon_cache";
import {
  buildAddAccountUrl,
  clearPreviousUserBrowserState,
  fetchSignedInAccounts,
  forgetKnownAccount,
  listSwitchableAccounts,
  readKnownAccounts,
  rememberAccounts,
  requestAccountSwitch,
  type AccountIdentity,
  type SignedInAccounts,
  type SwitchableAccount
} from "../../lib/auth/account_switcher";
import { LOCALE_CHANGE_EVENT, getRuntimeLocale } from "../../lib/i18n/config";
import { translate } from "../../lib/i18n/translate";
import { ACCOUNT_LIST_STYLES, renderAccountList, renderCurrentAccount } from "./user_icon_accounts";
// 右上ユーザーアイコン  +  ドロップダウンメニュー
//  - /api/user/profile で avatar_url / username / email を取得
//  - カスタム画像がある場合はデフォルト画像を先に出さない
//  - メニューを開くたびに /api/auth/accounts でログイン中のほかのアカウントを取得
// ────────────────────────────────────────────────

function normalizeText(value: unknown) {
  return typeof value === "string" ? value.trim() : "";
}

function hasCustomAvatar(value: unknown) {
  const avatarUrl = normalizeText(value);
  return avatarUrl !== "" && avatarUrl !== DEFAULT_AVATAR_URL;
}

const tpl = document.createElement("template");
tpl.innerHTML = `
  <style>
    :host {
      position: fixed;
      top: 10px;
      right: 10px;
      z-index: var(--z-user-menu, 70);
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
      width: 3rem;
      height: 3rem;
      border-radius: 50%;
      object-fit: cover;
      display: block;
    }
    /* ▼ dropdown */
    .dropdown {
      position: absolute;
      top: 3.5rem;
      right: 0;
      background: var(--surface-primary);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-m);
      box-shadow: var(--shadow-md);
      width: max-content;
      min-width: 15rem;
      max-width: min(20rem, calc(100vw - 20px));
      max-height: calc(100dvh - 4.5rem);
      overflow-y: auto;
      display: none;
      flex-direction: column;
      animation: fade .15s ease-out;
    }
    @keyframes fade { from { opacity: 0; transform: translateY(-5px);}
                      to   { opacity: 1; transform: translateY(0);} }
    .item {
      min-height: 2.75rem;
      box-sizing: border-box;
      padding: .6rem 1rem;
      font-size: var(--text-sm);
      text-decoration: none;
      color: var(--text-dark);
      display: flex;
      align-items: center;
      gap: .5rem;
      cursor: pointer;
    }
    .item:hover { background: var(--surface-tertiary); }
    .item-add-account { border-bottom: 1px solid var(--border-default); }
    .item:focus-visible,
    .account:focus-visible,
    .account-remove:focus-visible {
      outline: 2px solid var(--primary-dark);
      outline-offset: -2px;
    }
${ACCOUNT_LIST_STYLES}
  </style>

  <button class="btn">
    <img class="avatar" hidden>
  </button>

  <!-- 文言は表示言語に合わせて applyLocaleStrings が流し込む / applyLocaleStrings fills the copy in for the active display language -->
  <div class="dropdown">
    <div class="current"></div>
    <div class="accounts" role="group"></div>
    <div class="switch-error" role="alert" hidden></div>
    <a class="item item-add-account"><span aria-hidden="true">➕</span><span class="item-label"></span></a>
    <a class="item" href="/settings"><span aria-hidden="true">⚙️</span><span class="item-label"></span></a>
    <a class="item" href="/logout"><span aria-hidden="true">🚪</span><span class="item-label"></span></a>
  </div>
`;

async function postLogoutAndRedirect() {
  // 次の利用者（同一端末での別アカウント、または未ログイン）に前の利用者のデータを見せない。
  // The next person on this device (another account, or a guest) must never see the
  // outgoing user's data.
  clearPreviousUserBrowserState();
  // 認証状態キャッシュが "1"（ログイン中）のまま残っていると、次の利用者が
  // 認証確認より前にログイン済みUIとチャット本文を復元してしまう。
  // A stale "logged in" auth cache would let the next visitor's pre-auth
  // restore paint a logged-in UI (and chat text) before the server confirms it.
  try {
    localStorage.removeItem(STORAGE_KEYS.authStateCache);
    localStorage.removeItem(STORAGE_KEYS.authStateCachedAt);
  } catch {
    // localStorage が使えなくてもログアウト自体は継続する
  }
  try {
    const response = await resilientFetch("/logout", {
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
  private _handleLocaleChange: () => void;
  private settingsLabel: HTMLElement | null;
  private logoutLabel: HTMLElement | null;
  private addAccountLabel: HTMLElement | null;
  private currentAccountEl: HTMLElement;
  private accountsEl: HTMLElement;
  private switchErrorEl: HTMLElement;
  private currentAccount: AccountIdentity | null = null;
  private signedInAccounts: SignedInAccounts | null = null;
  private accountsRequestVersion = 0;
  private switching = false;

  constructor() {
    super();
    const root = this.attachShadow({ mode: "open" });
    root.append(tpl.content.cloneNode(true));

    const btn = root.querySelector(".btn") as HTMLButtonElement | null;
    const dropdown = root.querySelector(".dropdown") as HTMLDivElement | null;
    const avatarImg = root.querySelector(".avatar") as HTMLImageElement | null;

    const currentAccountEl = root.querySelector(".current") as HTMLElement | null;
    const accountsEl = root.querySelector(".accounts") as HTMLElement | null;
    const switchErrorEl = root.querySelector(".switch-error") as HTMLElement | null;
    const addAccountAnchor = root.querySelector(".item-add-account") as HTMLAnchorElement | null;

    if (!btn || !dropdown || !avatarImg || !currentAccountEl || !accountsEl || !switchErrorEl || !addAccountAnchor) {
      throw new Error("user-icon template is missing required elements");
    }

    this.btn = btn;
    this.dropdown = dropdown;
    this.avatarImg = avatarImg;
    this.currentAccountEl = currentAccountEl;
    this.accountsEl = accountsEl;
    this.switchErrorEl = switchErrorEl;
    addAccountAnchor.href = buildAddAccountUrl();
    this.addAccountLabel = addAccountAnchor.querySelector(".item-label");
    this.settingsLabel = root.querySelector('a[href="/settings"] .item-label');
    this.logoutLabel = root.querySelector('a[href="/logout"] .item-label');
    this._handleAuthState = this._handleAuthStateInternal.bind(this);
    this._handleLocaleChange = this.applyLocaleStrings.bind(this);
    this.applyLocaleStrings();
    this.setAvatarPending();

    // ドロップダウン開閉
    this.btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const opening = this.dropdown.style.display !== "flex";
      this.switchErrorEl.hidden = true;
      this.dropdown.style.display = opening ? "flex" : "none";
      if (opening) {
        void this.refreshAccounts();
      }
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
    // React ツリーの外にあるため、表示言語を切り替えても再描画されない。
    // LocaleProvider が発火するイベントを受けて文言を貼り直す。
    // This lives outside the React tree, so a language switch never re-renders it.
    // Re-apply the copy when the LocaleProvider announces the change.
    window.addEventListener(LOCALE_CHANGE_EVENT, this._handleLocaleChange);
    this.applyLocaleStrings();
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
    window.removeEventListener(LOCALE_CHANGE_EVENT, this._handleLocaleChange);
  }

  // メニューの文言を現在の表示言語で貼り直す / Re-apply the menu copy in the active display language
  private applyLocaleStrings() {
    const locale = getRuntimeLocale();
    this.btn.setAttribute("aria-label", translate(locale, "userMenu.open"));
    this.avatarImg.alt = translate(locale, "userMenu.avatarAlt");
    if (this.settingsLabel) this.settingsLabel.textContent = translate(locale, "userMenu.settings");
    if (this.logoutLabel) this.logoutLabel.textContent = translate(locale, "userMenu.logout");
    if (this.addAccountLabel) this.addAccountLabel.textContent = translate(locale, "userMenu.addAccount");
    this.switchErrorEl.textContent = translate(locale, "userMenu.switchFailed");
    this.renderAccounts();
  }

  // メニューを開くたびに取り直す。別タブでのログイン・ログアウトを反映するため。
  // Reloaded on every open so sign-ins and sign-outs from other tabs show up.
  private async refreshAccounts() {
    const requestVersion = ++this.accountsRequestVersion;
    const signedInAccounts = await fetchSignedInAccounts();
    if (requestVersion !== this.accountsRequestVersion || !signedInAccounts) {
      return;
    }
    rememberAccounts([...(signedInAccounts.current ? [signedInAccounts.current] : []), ...signedInAccounts.others]);
    this.signedInAccounts = signedInAccounts;
    this.renderAccounts();
  }

  private renderAccounts() {
    const current = this.signedInAccounts?.current ?? this.currentAccount;
    if (current) {
      renderCurrentAccount(this.currentAccountEl, current);
    } else {
      this.currentAccountEl.replaceChildren();
    }
    // ログイン中かどうかはサーバーの応答で決まるので、応答が来るまで一覧は出さない
    // Whether an account is signed in comes from the server, so wait for its answer
    if (!this.signedInAccounts) {
      this.accountsEl.replaceChildren();
      return;
    }
    renderAccountList(this.accountsEl, listSwitchableAccounts(this.signedInAccounts, readKnownAccounts()), {
      onSwitch: (account, row) => void this.switchTo(account, row),
      onForget: (account) => {
        forgetKnownAccount(account.userId);
        this.renderAccounts();
      }
    });
  }

  // 待機中のアカウントへ切り替える。サーバー側でセッションが切れていた場合は、
  // そのアカウントのログイン画面へ進める。
  // Switch to a parked account. When its server session is gone, fall through to the
  // login page for that account.
  private async switchTo(account: SwitchableAccount, row: HTMLElement) {
    if (this.switching) {
      return;
    }
    this.switching = true;
    row.setAttribute("aria-busy", "true");
    this.switchErrorEl.hidden = true;
    const result = await requestAccountSwitch(account.userId);
    if (result === "failed") {
      this.switching = false;
      row.removeAttribute("aria-busy");
      this.switchErrorEl.hidden = false;
      return;
    }
    if (result === "signed_out") {
      window.location.href = buildAddAccountUrl(account.email);
      return;
    }
    clearPreviousUserBrowserState();
    window.location.href = "/";
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
      clearCachedUserIconProfile();
      this.setAvatarPending();
      this.currentAccount = null;
      this.signedInAccounts = null;
      this.accountsRequestVersion += 1;
      this.renderAccounts();
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
      const res = await resilientFetch("/api/user/profile", { credentials: "same-origin" });
      if (requestVersion !== this._profileRequestVersion) {
        return;
      }
      if (res.status === 401) {
        // 未ログイン時は静かに何もしない
        this._profileLoaded = false;
        clearCachedUserIconProfile();
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
      const resolvedAvatar = hasCustomAvatar(avatar) ? avatar : DEFAULT_AVATAR_URL;

      writeCachedUserIconProfile(resolvedAvatar, name);
      this.setAvatar(resolvedAvatar, name);
      this.currentAccount = { username: name, email: normalizeText(data.email), avatarUrl: resolvedAvatar };
      this.renderAccounts();
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
    const cachedProfile = readCachedUserIconProfile();
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
    this.avatarImg.alt = translate(getRuntimeLocale(), "userMenu.avatarAlt");
  }

  private setAvatar(avatarUrl: string, username: string) {
    const locale = getRuntimeLocale();
    this.avatarImg.hidden = false;
    this.avatarImg.src = avatarUrl;
    this.avatarImg.alt = username
      ? translate(locale, "userMenu.avatarAltNamed", { username })
      : translate(locale, "userMenu.avatarAlt");
    this.setAttribute("data-avatar-ready", "true");
  }
}

if (!customElements.get("user-icon")) {
  customElements.define("user-icon", UserIcon);
}

export {};
