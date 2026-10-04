// components/user_icon_accounts.ts
// 右上ユーザーメニューのうち、アカウント切り替え一覧の DOM を組み立てる。
// Builds the account switcher rows of the top-right user menu.
import { buildAddAccountUrl, type AccountIdentity, type SwitchableAccount } from "../../lib/auth/account_switcher";
import { getRuntimeLocale } from "../../lib/i18n/config";
import { translate } from "../../lib/i18n/translate";
import { DEFAULT_AVATAR_URL } from "../core/user_icon_cache";

export const ACCOUNT_LIST_STYLES = `
    .current,
    .account {
      display: flex;
      align-items: center;
      gap: .75rem;
      min-width: 0;
    }
    .current {
      padding: .875rem 1rem;
      border-bottom: 1px solid var(--border-default);
    }
    .account-avatar {
      flex: none;
      width: 2rem;
      height: 2rem;
      border-radius: 50%;
      object-fit: cover;
    }
    .current .account-avatar {
      width: 2.5rem;
      height: 2.5rem;
    }
    /* 表示中アカウントの大きいアイコンと、名前の書き出し位置を揃える */
    .account .account-avatar {
      margin: 0 .25rem;
    }
    .identity {
      display: flex;
      flex-direction: column;
      min-width: 0;
      flex: 1;
      text-align: left;
    }
    .identity-name,
    .identity-email {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .identity-name {
      font-size: var(--text-sm);
      font-weight: 600;
      color: var(--text-dark);
    }
    .identity-email,
    .account-status {
      font-size: var(--text-2xs);
      color: var(--text-secondary);
    }
    .accounts {
      display: flex;
      flex-direction: column;
      border-bottom: 1px solid var(--border-default);
    }
    .accounts:empty {
      display: none;
    }
    .switch-error {
      padding: .5rem 1rem;
      font-size: var(--text-2xs);
      color: var(--danger-color);
      border-bottom: 1px solid var(--border-default);
    }
    .switch-error[hidden] {
      display: none;
    }
    .account-row {
      display: flex;
      align-items: center;
    }
    .account {
      flex: 1;
      min-height: 3rem;
      padding: .375rem 1rem;
      border: none;
      background: transparent;
      font: inherit;
      color: inherit;
      text-decoration: none;
      cursor: pointer;
    }
    .account-remove {
      flex: none;
      width: 2.75rem;
      height: 2.75rem;
      border: none;
      border-radius: 50%;
      background: transparent;
      color: var(--text-secondary);
      font-size: var(--text-xl);
      line-height: 1;
      cursor: pointer;
    }
    .account:hover,
    .account-remove:hover {
      background: var(--surface-tertiary);
    }
    .account[aria-busy="true"] {
      cursor: progress;
    }
`;

type AccountListHandlers = {
  onSwitch: (account: SwitchableAccount, row: HTMLElement) => void;
  onForget: (account: SwitchableAccount) => void;
};

function displayName(account: AccountIdentity) {
  return account.username || account.email;
}

function buildIdentity(account: AccountIdentity, status = "") {
  const avatar = document.createElement("img");
  avatar.className = "account-avatar";
  avatar.src = account.avatarUrl || DEFAULT_AVATAR_URL;
  avatar.alt = "";

  const identity = document.createElement("span");
  identity.className = "identity";
  const name = document.createElement("span");
  name.className = "identity-name";
  name.textContent = displayName(account);
  identity.append(name);
  // 名前が未設定のときは名前の位置にメールを出すので、同じ文字列を二段に並べない
  // Without a username the email already stands in for the name, so do not repeat it
  if (account.username && account.email) {
    const email = document.createElement("span");
    email.className = "identity-email";
    email.textContent = account.email;
    identity.append(email);
  }
  if (status) {
    const statusLine = document.createElement("span");
    statusLine.className = "account-status";
    statusLine.textContent = status;
    identity.append(statusLine);
  }
  return [avatar, identity];
}

export function renderCurrentAccount(container: HTMLElement, account: AccountIdentity) {
  container.replaceChildren(...buildIdentity(account));
}

function buildSignedInRow(account: SwitchableAccount, handlers: AccountListHandlers) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "account";
  button.setAttribute("aria-label", translate(getRuntimeLocale(), "userMenu.switchAccount", { name: displayName(account) }));
  button.append(...buildIdentity(account));
  button.addEventListener("click", (event) => {
    // 切り替え中の表示を残すため、外側クリック扱いでメニューを閉じさせない
    // Keep the menu open so the in-progress state stays visible
    event.stopPropagation();
    handlers.onSwitch(account, button);
  });
  return button;
}

function buildSignedOutRow(account: SwitchableAccount, handlers: AccountListHandlers) {
  const locale = getRuntimeLocale();
  const link = document.createElement("a");
  link.className = "account";
  link.href = buildAddAccountUrl(account.email);
  link.setAttribute("aria-label", translate(locale, "userMenu.signInAgain", { name: displayName(account) }));
  link.append(...buildIdentity(account, translate(locale, "userMenu.signedOut")));

  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "account-remove";
  remove.setAttribute("aria-label", translate(locale, "userMenu.removeAccount", { name: displayName(account) }));
  remove.textContent = "×";
  remove.addEventListener("click", (event) => {
    // 一覧から外すだけなので、メニューは開いたままにする
    // Removing an entry keeps the menu open
    event.stopPropagation();
    handlers.onForget(account);
  });
  return [link, remove];
}

export function renderAccountList(container: HTMLElement, accounts: SwitchableAccount[], handlers: AccountListHandlers) {
  container.setAttribute("aria-label", translate(getRuntimeLocale(), "userMenu.otherAccounts"));
  container.replaceChildren(
    ...accounts.map((account) => {
      const row = document.createElement("div");
      row.className = "account-row";
      if (account.signedIn) {
        row.append(buildSignedInRow(account, handlers));
      } else {
        row.append(...buildSignedOutRow(account, handlers));
      }
      return row;
    })
  );
}
