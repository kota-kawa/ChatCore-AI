// ActionMenu と ChatActionMenu が共有する、メニューの開閉・ナビゲーションのクリック処理と、ナビ用ボタンのアイコン。
// Click handling (outside-click close, navigation) and nav button icons shared by ActionMenu and ChatActionMenu.

// ナビ用 3 ボタン（共有・チャット・メモ）の SVG。テンプレートの <button> の中身として、そのまま差し込む。
// SVGs of the three nav buttons (share, chat, memo); inserted as-is as the content of the template's <button>.
export const NAV_SHARE_ICON_SVG = `      <svg viewBox="0 0 24 24">
        <path d="M18 16.08c-.76 0-1.44.3-1.96.77L8.91 12.7a3.048 3.048 0 0 0 0-1.39l7.13-4.17A3 3 0 1 0 14 5a3 3 0 0 0 .05.52l-7.14 4.18a3 3 0 1 0 0 4.6l7.14 4.18c-.03.17-.05.34-.05.52a3 3 0 1 0 3-2.92Z" />
      </svg>`;

export const NAV_STAR_ICON_SVG = `      <svg viewBox="0 0 24 24">
        <path d="M12,17.27L18.18,21L16.54,13.97 L22,9.24L14.81,8.62L12,2 L9.19,8.62L2,9.24L7.45,13.97 L5.82,21L12,17.27Z" />
      </svg>`;

export const NAV_MEMO_ICON_SVG = `      <svg viewBox="0 0 24 24">
        <path d="M19 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h9l7-7V5a2 2 0 0 0-2-2Zm-5 14v-5h5l-5 5Z" />
      </svg>`;

// メニュー外のクリックで開閉チェックボックスを閉じ、[data-nav-href] のボタンで chatcore:navigate を通知する。
// connect / disconnect は同じ関数参照で購読と解除を行うので、ホストの connectedCallback / disconnectedCallback から呼ぶ。
// Closes the toggle checkbox on outside clicks and announces chatcore:navigate for [data-nav-href] buttons.
// connect / disconnect subscribe and unsubscribe with the same function references; call them from the host's
// connectedCallback / disconnectedCallback.
export function bindPopupMenuClicks(host: HTMLElement, getToggle: () => HTMLInputElement | null) {
  const onDocumentClick = (event: MouseEvent) => {
    const toggle = getToggle();
    if (toggle?.checked && !event.composedPath().includes(host)) {
      toggle.checked = false;
    }
  };
  const onNavigationClick = (event: Event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;

    const button = target.closest<HTMLButtonElement>("[data-nav-href]");
    const href = button?.dataset.navHref;
    if (!href) return;

    event.preventDefault();
    const toggle = getToggle();
    if (toggle) {
      toggle.checked = false;
    }
    const shouldFallbackToDocumentNavigation = host.dispatchEvent(new CustomEvent("chatcore:navigate", {
      bubbles: true,
      cancelable: true,
      composed: true,
      detail: { href }
    }));
    if (shouldFallbackToDocumentNavigation) {
      window.location.href = href;
    }
  };

  return {
    connect() {
      document.addEventListener("click", onDocumentClick);
      host.shadowRoot?.addEventListener("click", onNavigationClick);
    },
    disconnect() {
      document.removeEventListener("click", onDocumentClick);
      host.shadowRoot?.removeEventListener("click", onNavigationClick);
    }
  };
}
