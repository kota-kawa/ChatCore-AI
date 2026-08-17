import { useCallback, useEffect, useId, useRef, useState } from "react";

import { useTranslation } from "../../contexts/locale_context";

type SetupAttachMenuProps = {
  // メニュー自体を開けない状態（チャット起動中など）/ Disables opening the menu (e.g. while a chat is launching)
  disabled: boolean;
  // 添付上限に達した場合はファイル添付の項目だけを無効化する / Only the file item is disabled once the attachment limit is reached
  fileItemDisabled: boolean;
  // メモ/マイコンテキスト参照が有効か / Whether the memo & My Context lookup is on
  memoLookupEnabled: boolean;
  // 自分のメモは本人しか読めないため、未ログインでは選べない / Memos are owner-only, so the item is unavailable when logged out
  memoItemDisabled: boolean;
  // 共有プロンプト参照が有効か / Whether the shared-prompt lookup is on
  sharedPromptLookupEnabled: boolean;
  // 画面ごとのボタンスタイル。既定値はセットアップ画面用 / Per-surface trigger style; setup is the default
  triggerClassName?: string;
  onToggleMemoLookup: () => void;
  onToggleSharedPromptLookup: () => void;
  onSelectFile: () => void;
};

type KnowledgeLookupChipsProps = {
  memoLookupEnabled: boolean;
  sharedPromptLookupEnabled: boolean;
  onToggleMemoLookup: () => void;
  onToggleSharedPromptLookup: () => void;
};

// 入力欄のクリップボタンから開く添付メニュー。メモ・共有プロンプト・ファイル添付を並べる。
// Attachment menu opened from the composer's paperclip button, listing memo, shared prompt, and file entries.
export function SetupAttachMenu({
  disabled,
  fileItemDisabled,
  memoLookupEnabled,
  memoItemDisabled,
  sharedPromptLookupEnabled,
  triggerClassName = "setup-attach-btn",
  onToggleMemoLookup,
  onToggleSharedPromptLookup,
  onSelectFile,
}: SetupAttachMenuProps) {
  const { t } = useTranslation();
  const [isOpen, setIsOpen] = useState(false);
  const menuId = `setup-attach-menu-${useId().replace(/:/g, "")}`;
  const containerRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);

  const closeMenu = useCallback(() => {
    setIsOpen(false);
  }, []);

  // メニュー外のクリックと Escape キーで閉じる / Close on outside click and on Escape
  useEffect(() => {
    if (!isOpen) return;

    const handlePointerDown = (event: PointerEvent) => {
      const container = containerRef.current;
      if (!container) return;
      if (event.target instanceof Node && container.contains(event.target)) return;
      closeMenu();
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      closeMenu();
      triggerRef.current?.focus();
    };

    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [closeMenu, isOpen]);

  // メニューを開けなくなったら開いたままにしない / Never leave the menu open once it can no longer be opened
  useEffect(() => {
    if (disabled) closeMenu();
  }, [closeMenu, disabled]);

  return (
    <div className="setup-attach-menu" ref={containerRef}>
      <button
        ref={triggerRef}
        type="button"
        className={triggerClassName}
        aria-label={t("home.attachMenu.open")}
        aria-haspopup="menu"
        aria-expanded={isOpen ? "true" : "false"}
        aria-controls={menuId}
        data-tooltip={t("home.attachMenu.open")}
        data-tooltip-placement="top"
        disabled={disabled}
        onClick={() => {
          setIsOpen((previous) => !previous);
        }}
      >
        <i className="bi bi-paperclip" aria-hidden="true"></i>
      </button>

      <div
        id={menuId}
        className={`setup-attach-menu__list ${isOpen ? "is-open" : ""}`.trim()}
        role="menu"
        aria-hidden={isOpen ? "false" : "true"}
      >
        {/* メモは参照モードのトグル。オンの間だけ回答がメモ/マイコンテキストを検索する。 */}
        {/* Memo toggles the lookup mode: while it is on, answers search the memos and My Context. */}
        <button
          type="button"
          className={`setup-attach-menu__item ${memoLookupEnabled ? "is-active" : ""}`.trim()}
          role="menuitemcheckbox"
          aria-checked={memoLookupEnabled ? "true" : "false"}
          tabIndex={isOpen ? 0 : -1}
          disabled={memoItemDisabled}
          title={memoItemDisabled ? t("home.attachMenu.memoLoginRequired") : undefined}
          onClick={() => {
            closeMenu();
            onToggleMemoLookup();
          }}
        >
          <i className="bi bi-journal-text setup-attach-menu__icon" aria-hidden="true"></i>
          <span>{t("home.attachMenu.memo")}</span>
          {memoLookupEnabled && (
            <i className="bi bi-check2 setup-attach-menu__check" aria-hidden="true"></i>
          )}
        </button>

        {/* 共有プロンプトも参照モードのトグル。公開データなので未ログインでも使える。 */}
        {/* Shared prompts toggle a lookup mode too; the data is public, so guests can use it. */}
        <button
          type="button"
          className={`setup-attach-menu__item ${sharedPromptLookupEnabled ? "is-active" : ""}`.trim()}
          role="menuitemcheckbox"
          aria-checked={sharedPromptLookupEnabled ? "true" : "false"}
          tabIndex={isOpen ? 0 : -1}
          onClick={() => {
            closeMenu();
            onToggleSharedPromptLookup();
          }}
        >
          <i className="bi bi-chat-square-quote setup-attach-menu__icon" aria-hidden="true"></i>
          <span>{t("home.attachMenu.sharedPrompt")}</span>
          {sharedPromptLookupEnabled && (
            <i className="bi bi-check2 setup-attach-menu__check" aria-hidden="true"></i>
          )}
        </button>

        <button
          type="button"
          className="setup-attach-menu__item"
          role="menuitem"
          tabIndex={isOpen ? 0 : -1}
          disabled={fileItemDisabled}
          onClick={() => {
            closeMenu();
            onSelectFile();
          }}
        >
          <i className="bi bi-paperclip setup-attach-menu__icon" aria-hidden="true"></i>
          <span>{t("home.attachMenu.file")}</span>
        </button>
      </div>
    </div>
  );
}

// メモ・共有プロンプトの参照中状態を入力欄内に表示するチップ。
// Chips showing which memo and shared-prompt lookups are active in the composer.
export function KnowledgeLookupChips({
  memoLookupEnabled,
  sharedPromptLookupEnabled,
  onToggleMemoLookup,
  onToggleSharedPromptLookup,
}: KnowledgeLookupChipsProps) {
  const { t } = useTranslation();

  if (!memoLookupEnabled && !sharedPromptLookupEnabled) return null;

  return (
    <div className="setup-knowledge-chip-row">
      {memoLookupEnabled && (
        <span className="setup-knowledge-chip">
          <i className="bi bi-journal-text setup-knowledge-chip__icon" aria-hidden="true"></i>
          <span className="setup-knowledge-chip__label">{t("home.attachMenu.memoActive")}</span>
          <button
            type="button"
            className="setup-knowledge-chip__remove"
            aria-label={t("home.attachMenu.memoTurnOff")}
            onClick={onToggleMemoLookup}
          >
            <i className="bi bi-x" aria-hidden="true"></i>
          </button>
        </span>
      )}
      {sharedPromptLookupEnabled && (
        <span className="setup-knowledge-chip">
          <i className="bi bi-chat-square-quote setup-knowledge-chip__icon" aria-hidden="true"></i>
          <span className="setup-knowledge-chip__label">{t("home.attachMenu.sharedPromptActive")}</span>
          <button
            type="button"
            className="setup-knowledge-chip__remove"
            aria-label={t("home.attachMenu.sharedPromptTurnOff")}
            onClick={onToggleSharedPromptLookup}
          >
            <i className="bi bi-x" aria-hidden="true"></i>
          </button>
        </span>
      )}
    </div>
  );
}

export default SetupAttachMenu;
