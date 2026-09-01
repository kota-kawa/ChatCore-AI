import type { FlashState } from "../../lib/memo/types";
import { ShareDialogContent } from "../ui/share_dialog_content";
import { useTranslation } from "../../contexts/locale_context";

type MemoShareModalProps = {
  isShareModalOpen: boolean;
  closeShareModal: () => void;
  shareUrl: string;
  shareStatus: FlashState | null;
  copyShareLink: () => Promise<boolean>;
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
  const { t } = useTranslation();
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
            <button type="button" className="memo-share-modal__close cc-share-modal__close" aria-label={t("memo.closeShare")} onClick={closeShareModal}>
              <i className="bi bi-x-lg"></i>
            </button>
            <header className="memo-share-modal__header cc-share-modal__header">
              <h3 id="memoShareTitle">{t("memo.share")}</h3>
              <p className="cc-share-modal__lead">
                {t("memo.shareDescription")}
              </p>
            </header>
            <ShareDialogContent
              bodyClassName="memo-share-modal__body"
              shareUrl={shareUrl}
              shareLoading={shareLoading}
              shareStatus={shareStatus ? { text: shareStatus.text, isError: shareStatus.type === "error" } : null}
              shareStatusClassName="memo-share-modal__status cc-share-modal__status"
              shareStatusErrorClassName="memo-share-modal__status--error cc-share-modal__status--error"
              linkInputId="memo-share-link-input"
              linkPlaceholder={t("memo.preparingShareLink")}
              onCopyLink={copyShareLink}
              copyLabel={t("memo.copyLink")}
              copiedLabel={t("common.copied")}
              socialLinks={shareSnsLinks}
              supportsNativeShare={supportsNativeShare}
              nativeShareLabel={t("memo.shareOnDevice")}
              onNativeShare={openNativeShareSheet}
            />
          </div>
        </div>
  );
}
