import type { ShareStatus } from "../../../lib/chat_page/types";
import { ModalCloseButton } from "../../ui/modal_close_button";
import { ModalShell } from "../../ui/modal_shell";
import { useTranslation } from "../../../contexts/locale_context";

// チャット共有モーダルのprops型定義
// Props type definition for the chat share modal
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

// チャット履歴を共有するためのリンク生成・コピー・SNSシェアを提供するモーダルコンポーネント
// Modal component for sharing chat history by generating, copying, and sharing on SNS
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
  const { locale, t } = useTranslation();

  return (
    <ModalShell
      isOpen={shareModalOpen}
      onClose={closeShareModal}
      id="chat-share-modal"
      className="chat-share-modal cc-share-modal"
      labelledBy="chat-share-title"
      initialFocusSelector="#chat-share-copy-btn"
    >
      <div className="chat-share-modal__content cc-share-modal__content" tabIndex={-1}>
        <ModalCloseButton
          id="chat-share-close-btn"
          className="chat-share-close-btn cc-share-modal__close"
          label={t("chat.closeModal")}
          onClick={closeShareModal}
        />

        <header className="chat-share-modal__header cc-share-modal__header">
          <h2 id="chat-share-title">{t("chat.shareTitle")}</h2>
          <p className="chat-share-modal__desc cc-share-modal__lead">
            {t("chat.shareDescription")}
          </p>
        </header>

        <div className="chat-share-modal__body cc-share-modal__body">
          {/* 共有リンクと、その右端に収めたコピーボタン / Share link with the copy button pinned to its right edge */}
          <div className="cc-share-modal__field">
            <input
              type="text"
              id="chat-share-link-input"
              readOnly
              placeholder={locale === "en" ? "Preparing share link" : "共有リンクを準備しています"}
              value={shareUrl}
            />
            <button
              type="button"
              id="chat-share-copy-btn"
              className="cc-share-modal__copy"
              aria-label={t("chat.copyLink")}
              title={t("chat.copyLink")}
              disabled={shareLoading}
              onClick={copyShareLink}
            >
              <i className="bi bi-files" aria-hidden="true"></i>
            </button>
          </div>

          {/* 共有状態のステータスメッセージ / Share status message */}
          <p
            id="chat-share-status"
            className={`chat-share-status cc-share-modal__status ${shareStatus.error ? "chat-share-status--error cc-share-modal__status--error" : ""}`.trim()}
          >
            {shareStatus.message}
          </p>

          {/* 共有先（X / LINE / Facebook / 端末共有）/ Share destinations (X / LINE / Facebook / device share) */}
          <div className="cc-share-modal__channels">
            <a
              id="chat-share-sns-x"
              className="cc-share-modal__channel"
              target="_blank"
              rel="noopener noreferrer"
              href={shareXUrl}
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
              id="chat-share-sns-line"
              className="cc-share-modal__channel"
              target="_blank"
              rel="noopener noreferrer"
              href={shareLineUrl}
              title="LINE"
            >
              <i className="bi bi-chat-dots" aria-hidden="true"></i>
              <span className="sr-only">LINE</span>
            </a>
            <a
              id="chat-share-sns-facebook"
              className="cc-share-modal__channel"
              target="_blank"
              rel="noopener noreferrer"
              href={shareFacebookUrl}
              title="Facebook"
            >
              <i className="bi bi-facebook" aria-hidden="true"></i>
              <span className="sr-only">Facebook</span>
            </a>
            {/* Web Share APIが使える端末でのみ端末共有を表示 / Device share appears only when the Web Share API is available */}
            {supportsNativeShare ? (
              <button
                type="button"
                id="chat-share-web-btn"
                className="cc-share-modal__channel"
                aria-label={locale === "en" ? "Share from this device" : "端末で共有"}
                title={locale === "en" ? "Share from this device" : "端末で共有"}
                disabled={shareLoading}
                onClick={shareWithNativeSheet}
              >
                <i className="bi bi-box-arrow-up-right" aria-hidden="true"></i>
              </button>
            ) : null}
          </div>
        </div>
      </div>
    </ModalShell>
  );
}
