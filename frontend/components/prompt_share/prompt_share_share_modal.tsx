import { useCallback, type RefObject } from "react";

import { useTranslation } from "../../contexts/locale_context";
import { ModalCloseButton } from "../ui/modal_close_button";
import { ModalShell } from "../ui/modal_shell";
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
// 共通モーダル面（cc-modal）の小サイズで描く。
// Prompt share modal providing URL copy, native share, and SNS share options,
// drawn on the small shared modal surface (cc-modal).
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
  // 開いた直後はコピーボタンへフォーカスし、Enter だけで共有できるようにする
  // Focus the copy button on open so a single Enter shares the link
  const getInitialFocus = useCallback(() => promptShareCopyButtonRef.current, [promptShareCopyButtonRef]);

  return (
    <ModalShell
      isOpen={isOpen}
      onClose={onClose}
      id="promptShareModal"
      className="cc-modal cc-share-modal prompt-share-modal"
      labelledBy="promptShareModalTitle"
      overlayRef={promptShareModalRef}
      getInitialFocus={getInitialFocus}
    >
      <div className="cc-modal__panel cc-modal__panel--sm cc-share-modal__content" tabIndex={-1}>
        <header className="cc-modal__header cc-share-modal__header">
          <div className="cc-modal__heading">
            <h2 className="cc-modal__title" id="promptShareModalTitle">{t("promptShare.sharePrompt")}</h2>
            <p className="cc-modal__lead cc-share-modal__lead">{t("promptShare.shareHelp")}</p>
          </div>
          <ModalCloseButton id="closePromptShareModal" label={t("promptShare.shareModalClose")} onClick={onClose} />
        </header>

        <div className="cc-modal__body">
          <ShareDialogContent
            shareUrl={shareUrl}
            shareLoading={shareActionLoading}
            shareStatus={{ text: shareStatus.text, isError: shareStatus.isError }}
            shareStatusId="prompt-share-status"
            shareStatusClassName="cc-share-modal__status"
            shareStatusErrorClassName="cc-share-modal__status--error"
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
    </ModalShell>
  );
}
