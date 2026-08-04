import type { RefObject } from "react";
import { useTranslation } from "../../contexts/locale_context";

// SNSシェアリンクのURL一式（X・LINE・Facebook）
// Set of SNS share link URLs (X, LINE, Facebook)
type PromptShareLinks = {
  x: string;
  line: string;
  facebook: string;
};

// 共有操作の結果を表すステータス型（エラー有無とメッセージ）
// Status type for share action result (error flag and message)
type PromptShareStatus = {
  text: string;
  isError: boolean;
};

// 共有モーダルのプロップス
// Props for the share modal
type PromptShareShareModalProps = {
  isOpen: boolean;
  promptShareModalRef: RefObject<HTMLDivElement | null>;
  onClose: () => void;
  shareUrl: string;
  shareStatus: PromptShareStatus;
  shareActionLoading: boolean;
  promptShareCopyButtonRef: RefObject<HTMLButtonElement | null>;
  onCopyLink: () => Promise<void> | void;
  supportsNativeShare: boolean;
  onNativeShare: () => Promise<void> | void;
  shareSnsLinks: PromptShareLinks;
};

// プロンプト共有モーダル（URLコピー・ネイティブシェア・SNSシェアを提供）
// Prompt share modal providing URL copy, native share, and SNS share options
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
  const { t } = useTranslation();
  return (
    <div
      id="promptShareModal"
      className={`post-modal prompt-share-modal cc-share-modal${isOpen ? " show" : ""}`}
      role="dialog"
      aria-modal="true"
      aria-labelledby="promptShareModalTitle"
      aria-hidden={isOpen ? "false" : "true"}
      ref={promptShareModalRef}
      onClick={(event) => {
        {/* オーバーレイ背景クリックでモーダルを閉じる / Close modal on overlay background click */}
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <div className="post-modal-content prompt-share-dialog cc-share-modal__content" tabIndex={-1}>
        <button
          type="button"
          className="prompt-share-dialog__close cc-share-modal__close"
          id="closePromptShareModal"
          aria-label={t("promptShare.shareModalClose")}
          onClick={onClose}
        >
          <svg aria-hidden="true" viewBox="0 0 24 24" fill="currentColor">
            <path d="M18.3 5.71 12 12l6.3 6.29-1.41 1.42L10.59 13.4 4.29 19.7 2.88 18.3 9.17 12 2.88 5.71 4.29 4.3 10.59 10.6 16.9 4.29z" />
          </svg>
        </button>

        <header className="prompt-share-dialog__header cc-share-modal__header">
          <h2 id="promptShareModalTitle">{t("promptShare.sharePrompt")}</h2>
          <p className="prompt-share-dialog__lead cc-share-modal__lead">
            {t("promptShare.shareHelp")}
          </p>
        </header>

        <div className="prompt-share-dialog__body cc-share-modal__body">
          {/* 共有URLと、その右端に収めたコピーボタン / Share URL with the copy button pinned to its right edge */}
          <div className="cc-share-modal__field">
            <input
              type="text"
              id="prompt-share-link-input"
              readOnly
              placeholder={t("promptShare.preparingShareLink")}
              aria-label={t("promptShare.shareUrl")}
              value={shareUrl}
            />
            <button
              type="button"
              id="prompt-share-copy-btn"
              className="cc-share-modal__copy"
              aria-label={t("promptShare.copyLink")}
              title={t("promptShare.copyLink")}
              ref={promptShareCopyButtonRef}
              disabled={shareActionLoading}
              onClick={() => {
                void onCopyLink();
              }}
            >
              <i className="bi bi-files" aria-hidden="true"></i>
            </button>
          </div>

          {/* コピー・シェア操作のフィードバックメッセージ / Feedback message for copy/share actions */}
          <p
            id="prompt-share-status"
            className={`prompt-share-dialog__status cc-share-modal__status${shareStatus.isError ? " prompt-share-dialog__status--error cc-share-modal__status--error" : ""}`}
          >
            {shareStatus.text}
          </p>

          {/* 共有先（X・LINE・Facebook・端末共有） / Share destinations (X, LINE, Facebook, device share) */}
          <div className="cc-share-modal__channels">
            <a
              id="prompt-share-sns-x"
              className="cc-share-modal__channel"
              target="_blank"
              rel="noopener noreferrer"
              href={shareSnsLinks.x}
              title="X"
            >
              <svg className="share-x-icon" viewBox="0 0 24 24" aria-hidden="true">
                <path
                  fill="currentColor"
                  d="M18.901 1.153h3.68l-8.04 9.188L24 22.847h-7.406l-5.8-7.584-6.63 7.584H.48l8.6-9.83L0 1.154h7.594l5.243 6.932L18.901 1.153Zm-1.291 19.49h2.039L6.486 3.24H4.298L17.61 20.643Z"
                ></path>
              </svg>
              <span className="sr-only">X</span>
            </a>
            <a
              id="prompt-share-sns-line"
              className="cc-share-modal__channel"
              target="_blank"
              rel="noopener noreferrer"
              href={shareSnsLinks.line}
              title="LINE"
            >
              <i className="bi bi-chat-dots" aria-hidden="true"></i>
              <span className="sr-only">LINE</span>
            </a>
            <a
              id="prompt-share-sns-facebook"
              className="cc-share-modal__channel"
              target="_blank"
              rel="noopener noreferrer"
              href={shareSnsLinks.facebook}
              title="Facebook"
            >
              <i className="bi bi-facebook" aria-hidden="true"></i>
              <span className="sr-only">Facebook</span>
            </a>

            {/* Web Share APIが利用可能な場合のみネイティブシェアボタンを表示 / Native share button shown only when Web Share API is available */}
            {supportsNativeShare ? (
              <button
                type="button"
                id="prompt-share-web-btn"
                className="cc-share-modal__channel"
                aria-label={t("promptShare.shareOnDevice")}
                title={t("promptShare.shareOnDevice")}
                disabled={shareActionLoading}
                onClick={() => {
                  void onNativeShare();
                }}
              >
                <i className="bi bi-box-arrow-up-right" aria-hidden="true"></i>
              </button>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
