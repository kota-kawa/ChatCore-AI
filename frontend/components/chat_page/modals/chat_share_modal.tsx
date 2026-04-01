type ShareStatus = {
  message: string;
  error: boolean;
};

type ChatShareModalProps = {
  shareModalOpen: boolean;
  shareStatus: ShareStatus;
  shareUrl: string;
  shareLoading: boolean;
  supportsNativeShare: boolean;
  shareXUrl: string;
  shareLineUrl: string;
  shareFacebookUrl: string;
  closeShareModal: () => void;
  copyShareLink: () => void;
  shareWithNativeSheet: () => void;
};

export function ChatShareModal({
  shareModalOpen,
  shareStatus,
  shareUrl,
  shareLoading,
  supportsNativeShare,
  shareXUrl,
  shareLineUrl,
  shareFacebookUrl,
  closeShareModal,
  copyShareLink,
  shareWithNativeSheet,
}: ChatShareModalProps) {
  return (
    <div
      id="chat-share-modal"
      className="chat-share-modal"
      role="dialog"
      aria-modal="true"
      aria-hidden={shareModalOpen ? "false" : "true"}
      aria-labelledby="chat-share-title"
      style={{ display: shareModalOpen ? "flex" : "none" }}
      onClick={(event) => {
        if (event.target === event.currentTarget) {
          closeShareModal();
        }
      }}
    >
      <div className="chat-share-modal__content">
        <div className="chat-share-modal__header">
          <h5 id="chat-share-title">チャットを共有</h5>
          <button
            type="button"
            id="chat-share-close-btn"
            className="chat-share-close-btn"
            aria-label="共有モーダルを閉じる"
            onClick={closeShareModal}
          >
            <i className="bi bi-x-lg"></i>
          </button>
        </div>

        <p className="chat-share-modal__desc">
          共有リンクを作成すると、このチャットルームの履歴をURL経由で閲覧できます。
        </p>

        <div className="chat-share-link-row">
          <input
            type="text"
            id="chat-share-link-input"
            readOnly
            placeholder="共有リンクを準備しています"
            value={shareUrl}
          />
        </div>

        <p id="chat-share-status" className={`chat-share-status ${shareStatus.error ? "chat-share-status--error" : ""}`.trim()}>
          {shareStatus.message}
        </p>

        <div className="chat-share-actions">
          <button
            type="button"
            id="chat-share-copy-btn"
            className="primary-button chat-share-icon-btn"
            aria-label="リンクをコピー"
            title="リンクをコピー"
            disabled={shareLoading}
            onClick={copyShareLink}
          >
            <i className="bi bi-files" aria-hidden="true"></i>
          </button>
          <button
            type="button"
            id="chat-share-web-btn"
            className="primary-button chat-share-icon-btn"
            aria-label="端末で共有"
            title="端末で共有"
            disabled={shareLoading}
            onClick={shareWithNativeSheet}
            style={{ display: supportsNativeShare ? "inline-flex" : "none" }}
          >
            <i className="bi bi-box-arrow-up-right" aria-hidden="true"></i>
          </button>
        </div>

        <div className="chat-share-sns">
          <a id="chat-share-sns-x" target="_blank" rel="noopener noreferrer" href={shareXUrl}>
            <svg className="share-x-icon" viewBox="0 0 24 24" aria-hidden="true">
              <path
                fill="currentColor"
                d="M18.901 1.153h3.68l-8.04 9.188L24 22.847h-7.406l-5.8-7.584-6.63 7.584H.48l8.6-9.83L0 1.154h7.594l5.243 6.932L18.901 1.153Zm-1.291 19.49h2.039L6.486 3.24H4.298L17.61 20.643Z"
              ></path>
            </svg>
            <span>X</span>
          </a>
          <a id="chat-share-sns-line" target="_blank" rel="noopener noreferrer" href={shareLineUrl}>
            <i className="bi bi-chat-dots"></i>
            <span>LINE</span>
          </a>
          <a
            id="chat-share-sns-facebook"
            target="_blank"
            rel="noopener noreferrer"
            href={shareFacebookUrl}
          >
            <i className="bi bi-facebook"></i>
            <span>Facebook</span>
          </a>
        </div>
      </div>
    </div>
  );
}
