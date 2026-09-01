import type { RefObject } from "react";

import { useTranslation } from "../../contexts/locale_context";
import { ShareDialogContent } from "../ui/share_dialog_content";

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
  onCopyLink: () => Promise<boolean>;
  supportsNativeShare: boolean;
  onNativeShare: () => Promise<void> | void;
  shareSnsLinks: { x: string; line: string; facebook: string };
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
  shareSnsLinks,
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

        <ShareDialogContent
          bodyClassName="prompt-share-dialog__body"
          shareUrl={shareUrl}
          shareLoading={shareActionLoading}
          shareStatus={{ text: shareStatus.text, isError: shareStatus.isError }}
          shareStatusId="prompt-share-status"
          shareStatusClassName="prompt-share-dialog__status cc-share-modal__status"
          shareStatusErrorClassName="prompt-share-dialog__status--error cc-share-modal__status--error"
          linkInputId="prompt-share-link-input"
          linkInputAriaLabel={t("promptShare.shareUrl")}
          linkPlaceholder={t("promptShare.preparingShareLink")}
          copyButtonId="prompt-share-copy-btn"
          copyButtonRef={promptShareCopyButtonRef}
          onCopyLink={onCopyLink}
          copyLabel={t("promptShare.copyLink")}
          copiedLabel={t("common.copied")}
          socialLinks={shareSnsLinks}
          socialLinkIds={{
            x: "prompt-share-sns-x",
            line: "prompt-share-sns-line",
            facebook: "prompt-share-sns-facebook",
          }}
          supportsNativeShare={supportsNativeShare}
          nativeShareButtonId="prompt-share-web-btn"
          nativeShareLabel={t("promptShare.shareOnDevice")}
          onNativeShare={onNativeShare}
        />
      </div>
    </div>
  );
}
