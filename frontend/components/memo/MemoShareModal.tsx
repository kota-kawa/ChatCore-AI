import type { FlashState } from "../../lib/memo/types";
import { CopyButton } from "../ui/copy_button";
import { useTranslation } from "../../contexts/locale_context";

type MemoShareModalProps = {
  isShareModalOpen: boolean;
  closeShareModal: () => void;
  shareUrl: string;
  shareStatus: FlashState | null;
  copyShareLink: () => Promise<boolean>;
  openNativeShareSheet: () => Promise<void>;
  shareLoading: boolean;
  supportsNativeShare: boolean;
  shareSnsLinks: { x: string; line: string; facebook: string };
};

// ── Share modal ──
export function MemoShareModal({
  isShareModalOpen,
  closeShareModal,
  shareUrl,
  shareStatus,
  copyShareLink,
  openNativeShareSheet,
  shareLoading,
  supportsNativeShare,
  shareSnsLinks,
}: MemoShareModalProps) {
  const { t } = useTranslation();
  return (
        <div
          id="memo-share-modal"
          className={`memo-share-modal cc-share-modal${isShareModalOpen ? " is-visible" : ""}`}
          role="dialog"
          aria-modal="true"
          aria-hidden={isShareModalOpen ? "false" : "true"}
          aria-labelledby="memoShareTitle"
          onClick={(event) => {
            if (event.target === event.currentTarget) {
              closeShareModal();
            }
          }}
        >
          <div className="memo-share-modal__content cc-share-modal__content" tabIndex={-1}>
            <button type="button" className="memo-share-modal__close cc-share-modal__close" aria-label={t("memo.closeShare")} onClick={closeShareModal}>
              <i className="bi bi-x-lg"></i>
            </button>
            <header className="memo-share-modal__header cc-share-modal__header">
              <h3 id="memoShareTitle">{t("memo.share")}</h3>
              <p className="cc-share-modal__lead">
                {t("memo.shareDescription")}
              </p>
            </header>
            <div className="memo-share-modal__body cc-share-modal__body">
              {/* 共有リンクと、その右端に収めたコピーボタン / Share link with the copy button pinned to its right edge */}
              <div className="cc-share-modal__field">
                <input
                  id="memo-share-link-input"
                  type="text"
                  readOnly
                  value={shareUrl}
                  placeholder={t("memo.preparingShareLink")}
                />
                <CopyButton
                  onCopy={copyShareLink}
                  label={t("memo.copyLink")}
                  copiedLabel={t("common.copied")}
                  className="cc-share-modal__copy"
                  idleIcon="bi-files"
                  disabled={shareLoading || !shareUrl}
                />
              </div>
              {shareStatus && <p className={`memo-share-modal__status cc-share-modal__status memo-share-modal__status--${shareStatus.type}${shareStatus.type === "error" ? " cc-share-modal__status--error" : ""}`}>{shareStatus.text}</p>}
              {/* 共有先（X / LINE / Facebook / 端末共有） / Share destinations (X / LINE / Facebook / device share) */}
              <div className="cc-share-modal__channels">
                <a className="cc-share-modal__channel" target="_blank" rel="noopener noreferrer" href={shareSnsLinks.x} title="X">
                  <svg className="share-x-icon" viewBox="0 0 24 24" aria-hidden="true">
                    <path
                      fill="currentColor"
                      d="M18.901 1.153h3.68l-8.04 9.188L24 22.847h-7.406l-5.8-7.584-6.63 7.584H.48l8.6-9.83L0 1.154h7.594l5.243 6.932L18.901 1.153Zm-1.291 19.49h2.039L6.486 3.24H4.298L17.61 20.643Z"
                    ></path>
                  </svg>
                  <span className="sr-only">X</span>
                </a>
                <a className="cc-share-modal__channel" target="_blank" rel="noopener noreferrer" href={shareSnsLinks.line} title="LINE">
                  <i className="bi bi-chat-dots" aria-hidden="true"></i>
                  <span className="sr-only">LINE</span>
                </a>
                <a className="cc-share-modal__channel" target="_blank" rel="noopener noreferrer" href={shareSnsLinks.facebook} title="Facebook">
                  <i className="bi bi-facebook" aria-hidden="true"></i>
                  <span className="sr-only">Facebook</span>
                </a>
                {supportsNativeShare && (
                  <button
                    type="button"
                    className="cc-share-modal__channel"
                    aria-label={t("memo.shareOnDevice")}
                    title={t("memo.shareOnDevice")}
                    onClick={() => { void openNativeShareSheet(); }}
                    disabled={shareLoading || !shareUrl}
                  >
                    <i className="bi bi-box-arrow-up-right" aria-hidden="true"></i>
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
  );
}
