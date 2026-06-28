import type { FlashState } from "../../lib/memo/types";

type MemoShareModalProps = {
  isShareModalOpen: boolean;
  closeShareModal: () => void;
  shareUrl: string;
  shareStatus: FlashState | null;
  copyShareLink: () => Promise<void>;
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
            <button type="button" className="memo-share-modal__close cc-share-modal__close" aria-label="共有モーダルを閉じる" onClick={closeShareModal}>
              <i className="bi bi-x-lg"></i>
            </button>
            <header className="memo-share-modal__header cc-share-modal__header">
              <h3 id="memoShareTitle">メモを共有</h3>
              <p className="cc-share-modal__lead">
                このメモ専用のURLをコピーしたり、そのまま共有できます。
              </p>
            </header>
            <div className="memo-share-modal__body cc-share-modal__body">
              <div className="memo-share-modal__row cc-share-modal__row">
                <input
                  id="memo-share-link-input"
                  type="text"
                  readOnly
                  value={shareUrl}
                  placeholder="共有リンクを準備しています"
                />
              </div>
              {shareStatus && <p className={`memo-share-modal__status cc-share-modal__status memo-share-modal__status--${shareStatus.type}${shareStatus.type === "error" ? " cc-share-modal__status--error" : ""}`}>{shareStatus.text}</p>}
              <div className="memo-share-modal__actions cc-share-modal__actions">
                <button type="button" className="primary-button memo-share-modal__icon-btn cc-share-modal__icon-btn" aria-label="リンクをコピー" title="リンクをコピー" onClick={() => { void copyShareLink(); }} disabled={shareLoading || !shareUrl}><i className="bi bi-files"></i></button>
                {supportsNativeShare && (
                  <button type="button" className="primary-button memo-share-modal__icon-btn cc-share-modal__icon-btn" aria-label="端末で共有" title="端末で共有" onClick={() => { void openNativeShareSheet(); }} disabled={shareLoading || !shareUrl}><i className="bi bi-box-arrow-up-right"></i></button>
                )}
              </div>
              <div className="memo-share-modal__sns cc-share-modal__sns">
                <a target="_blank" rel="noopener noreferrer" href={shareSnsLinks.x}>
                  <svg className="share-x-icon" viewBox="0 0 24 24" aria-hidden="true">
                    <path
                      fill="currentColor"
                      d="M18.901 1.153h3.68l-8.04 9.188L24 22.847h-7.406l-5.8-7.584-6.63 7.584H.48l8.6-9.83L0 1.154h7.594l5.243 6.932L18.901 1.153Zm-1.291 19.49h2.039L6.486 3.24H4.298L17.61 20.643Z"
                    ></path>
                  </svg>
                  <span>X</span>
                </a>
                <a target="_blank" rel="noopener noreferrer" href={shareSnsLinks.line}>
                  <i className="bi bi-chat-dots"></i>
                  <span>LINE</span>
                </a>
                <a target="_blank" rel="noopener noreferrer" href={shareSnsLinks.facebook}>
                  <i className="bi bi-facebook"></i>
                  <span>Facebook</span>
                </a>
              </div>
            </div>
          </div>
        </div>
  );
}
