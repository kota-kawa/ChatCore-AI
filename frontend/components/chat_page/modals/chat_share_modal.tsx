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
// 共通モーダル面（cc-modal）の小サイズで描き、中身はプロンプト共有の共有モーダルと同じ cc-share-modal。
// Modal component for sharing chat history by generating, copying, and sharing on SNS.
// Drawn on the small shared modal surface (cc-modal); the body is the same cc-share-modal as Prompt Share.
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
      className="cc-modal cc-share-modal chat-share-modal"
      labelledBy="chat-share-title"
      initialFocusSelector="#chat-share-copy-btn"
    >
      <div className="cc-modal__panel cc-modal__panel--sm cc-share-modal__content" tabIndex={-1}>
        <header className="cc-modal__header cc-share-modal__header">
          <div className="cc-modal__heading">
            <h2 className="cc-modal__title" id="chat-share-title">{t("chat.shareTitle")}</h2>
            <p className="cc-modal__lead cc-share-modal__lead">{t("chat.shareDescription")}</p>
          </div>
          <ModalCloseButton id="chat-share-close-btn" label={t("chat.closeModal")} onClick={closeShareModal} />
        </header>

        <div className="cc-modal__body">
          <ShareDialogContent
            shareUrl={shareUrl}
            shareLoading={shareLoading}
            shareStatus={{ text: shareStatus.message, isError: shareStatus.error }}
            shareStatusId="chat-share-status"
            shareStatusClassName="cc-share-modal__status"
            shareStatusErrorClassName="cc-share-modal__status--error"
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
      </div>
    </ModalShell>
  );
}
