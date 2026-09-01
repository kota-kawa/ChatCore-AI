import type { ShareStatus } from "../../../lib/chat_page/types";
import { ShareDialogContent } from "../../ui/share_dialog_content";
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
  copyShareLink: () => Promise<boolean>;
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

        <ShareDialogContent
          bodyClassName="chat-share-modal__body"
          shareUrl={shareUrl}
          shareLoading={shareLoading}
          shareStatus={{ text: shareStatus.message, isError: shareStatus.error }}
          shareStatusId="chat-share-status"
          shareStatusClassName="chat-share-status cc-share-modal__status"
          shareStatusErrorClassName="chat-share-status--error cc-share-modal__status--error"
          linkInputId="chat-share-link-input"
          linkPlaceholder={locale === "en" ? "Preparing share link" : "共有リンクを準備しています"}
          copyButtonId="chat-share-copy-btn"
          onCopyLink={copyShareLink}
          copyLabel={t("chat.copyLink")}
          copiedLabel={t("common.copied")}
          socialLinks={{ x: shareXUrl, line: shareLineUrl, facebook: shareFacebookUrl }}
          socialLinkIds={{ x: "chat-share-sns-x", line: "chat-share-sns-line", facebook: "chat-share-sns-facebook" }}
          supportsNativeShare={supportsNativeShare}
          nativeShareButtonId="chat-share-web-btn"
          nativeShareLabel={locale === "en" ? "Share from this device" : "端末で共有"}
          onNativeShare={shareWithNativeSheet}
        />
      </div>
    </ModalShell>
  );
}
