import type { RefObject } from "react";

type PromptShareLinks = {
  x: string;
  line: string;
  facebook: string;
};

type PromptShareStatus = {
  text: string;
  isError: boolean;
};

type PromptShareShareModalProps = {
  isOpen: boolean;
  promptShareModalRef: RefObject<HTMLDivElement>;
  onClose: () => void;
  shareUrl: string;
  shareStatus: PromptShareStatus;
  shareActionLoading: boolean;
  promptShareCopyButtonRef: RefObject<HTMLButtonElement>;
  onCopyLink: () => Promise<void> | void;
  supportsNativeShare: boolean;
  onNativeShare: () => Promise<void> | void;
  shareSnsLinks: PromptShareLinks;
};

export function PromptShareShareModal({
  isOpen,
  promptShareModalRef,
  onClose,
  shareUrl,
  shareStatus,
  shareActionLoading,
  promptShareCopyButtonRef,
  onCopyLink,
  supportsNativeShare,
  onNativeShare,
  shareSnsLinks
}: PromptShareShareModalProps) {
  return (
    <div
      id="promptShareModal"
      className={`post-modal prompt-share-modal${isOpen ? " show" : ""}`}
      role="dialog"
      aria-modal="true"
      aria-labelledby="promptShareModalTitle"
      aria-hidden={isOpen ? "false" : "true"}
      ref={promptShareModalRef}
      onClick={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <div className="post-modal-content prompt-share-dialog" tabIndex={-1}>
        <button
          type="button"
          className="prompt-share-dialog__close"
          id="closePromptShareModal"
          aria-label="共有モーダルを閉じる"
          onClick={onClose}
        >
          <svg aria-hidden="true" viewBox="0 0 24 24" fill="currentColor">
            <path d="M18.3 5.71 12 12l6.3 6.29-1.41 1.42L10.59 13.4 4.29 19.7 2.88 18.3 9.17 12 2.88 5.71 4.29 4.3 10.59 10.6 16.9 4.29z" />
          </svg>
        </button>

        <header className="prompt-share-dialog__header">
          <h2 id="promptShareModalTitle">プロンプトを共有</h2>
          <p className="prompt-share-dialog__lead">
            このプロンプト専用のURLをコピーしたり、そのまま共有できます。
          </p>
        </header>

        <div className="prompt-share-dialog__body">
          <div className="prompt-share-dialog__row">
            <input
              type="text"
              id="prompt-share-link-input"
              readOnly
              placeholder="共有リンクを準備しています"
              value={shareUrl}
            />
          </div>

          <p
            id="prompt-share-status"
            className={`prompt-share-dialog__status${shareStatus.isError ? " prompt-share-dialog__status--error" : ""}`}
          >
            {shareStatus.text}
          </p>

          <div className="prompt-share-dialog__actions">
            <button
              type="button"
              id="prompt-share-copy-btn"
              className="submit-btn prompt-share-icon-btn"
              aria-label="リンクをコピー"
              title="リンクをコピー"
              ref={promptShareCopyButtonRef}
              disabled={shareActionLoading}
              onClick={() => {
                void onCopyLink();
              }}
            >
              <i className="bi bi-files" aria-hidden="true"></i>
            </button>

            {supportsNativeShare ? (
              <button
                type="button"
                id="prompt-share-web-btn"
                className="submit-btn prompt-share-icon-btn"
                aria-label="端末で共有"
                title="端末で共有"
                disabled={shareActionLoading}
                onClick={() => {
                  void onNativeShare();
                }}
              >
                <i className="bi bi-box-arrow-up-right" aria-hidden="true"></i>
              </button>
            ) : null}
          </div>

          <div className="prompt-share-dialog__sns">
            <a id="prompt-share-sns-x" target="_blank" rel="noopener noreferrer" href={shareSnsLinks.x}>
              <svg className="share-x-icon" viewBox="0 0 24 24" aria-hidden="true">
                <path
                  fill="currentColor"
                  d="M18.901 1.153h3.68l-8.04 9.188L24 22.847h-7.406l-5.8-7.584-6.63 7.584H.48l8.6-9.83L0 1.154h7.594l5.243 6.932L18.901 1.153Zm-1.291 19.49h2.039L6.486 3.24H4.298L17.61 20.643Z"
                ></path>
              </svg>
              <span>X</span>
            </a>
            <a id="prompt-share-sns-line" target="_blank" rel="noopener noreferrer" href={shareSnsLinks.line}>
              <i className="bi bi-chat-dots"></i>
              <span>LINE</span>
            </a>
            <a
              id="prompt-share-sns-facebook"
              target="_blank"
              rel="noopener noreferrer"
              href={shareSnsLinks.facebook}
            >
              <i className="bi bi-facebook"></i>
              <span>Facebook</span>
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}
