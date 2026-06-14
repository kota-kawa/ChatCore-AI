import { useCallback, useRef } from "react";

import { useModalFocusTrap } from "../../../hooks/use_modal_focus_trap";
import type { ShareStatus } from "../../../lib/chat_page/types";
import { ModalCloseButton } from "../../ui/modal_close_button";

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
  const modalRef = useRef<HTMLDivElement | null>(null);

  // 初期フォーカスをコピーボタンに設定する
  // Set initial focus to the copy button
  const getInitialFocus = useCallback(() => {
    return modalRef.current?.querySelector<HTMLElement>("#chat-share-copy-btn") ?? null;
  }, []);

  // フォーカストラップとEscキーでの閉じる動作を設定する
  // Set up focus trap and close behavior on Escape key
  useModalFocusTrap({
    isOpen: shareModalOpen,
    containerRef: modalRef,
    getInitialFocus,
    onEscape: closeShareModal,
  });

  return (
    <div
      ref={modalRef}
      id="chat-share-modal"
      className={`chat-share-modal modal-base cc-share-modal ${shareModalOpen ? "is-open" : ""}`.trim()}
      role="dialog"
      aria-modal="true"
      aria-hidden={shareModalOpen ? "false" : "true"}
      aria-labelledby="chat-share-title"
      tabIndex={-1}
      // 背景クリックでモーダルを閉じる / Close modal on backdrop click
      onClick={(event) => {
        if (event.target === event.currentTarget) {
          closeShareModal();
        }
      }}
    >
      <div className="chat-share-modal__content cc-share-modal__content" tabIndex={-1}>
        <ModalCloseButton
          id="chat-share-close-btn"
          className="chat-share-close-btn cc-share-modal__close"
          label="共有モーダルを閉じる"
          onClick={closeShareModal}
        />

        <header className="chat-share-modal__header cc-share-modal__header">
          <h2 id="chat-share-title">チャットを共有</h2>
          <p className="chat-share-modal__desc cc-share-modal__lead">
            共有リンクを作成すると、このチャットルームの履歴をURL経由で閲覧できます。
          </p>
        </header>

        <div className="chat-share-modal__body cc-share-modal__body">
          {/* 共有リンクの表示欄 / Share link display field */}
          <div className="chat-share-link-row cc-share-modal__row">
            <input
              type="text"
              id="chat-share-link-input"
              readOnly
              placeholder="共有リンクを準備しています"
              value={shareUrl}
            />
          </div>

          {/* 共有状態のステータスメッセージ / Share status message */}
          <p
            id="chat-share-status"
            className={`chat-share-status cc-share-modal__status ${shareStatus.error ? "chat-share-status--error cc-share-modal__status--error" : ""}`.trim()}
          >
            {shareStatus.message}
          </p>

          {/* リンクコピーと端末共有ボタン / Link copy and device share buttons */}
          <div className="chat-share-actions cc-share-modal__actions">
            <button
              type="button"
              id="chat-share-copy-btn"
              className="primary-button chat-share-icon-btn cc-share-modal__icon-btn"
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
              className="primary-button chat-share-icon-btn cc-share-modal__icon-btn"
              aria-label="端末で共有"
              title="端末で共有"
              disabled={shareLoading}
              onClick={shareWithNativeSheet}
              hidden={!supportsNativeShare}
            >
              <i className="bi bi-box-arrow-up-right" aria-hidden="true"></i>
            </button>
          </div>

          {/* SNS共有リンク（X / LINE / Facebook）/ SNS share links (X / LINE / Facebook) */}
          <div className="chat-share-sns cc-share-modal__sns">
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
    </div>
  );
}
