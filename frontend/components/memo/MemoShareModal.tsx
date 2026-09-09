import { ModalCloseButton } from "../ui/modal_close_button";
import { ModalShell } from "../ui/modal_shell";
import { ShareDialogContent } from "../ui/share_dialog_content";
import { useTranslation } from "../../contexts/locale_context";
import { useMemoPageModalsContext } from "../../contexts/memo_page/memo_page_context";

// ── Share modal ──
// 共通モーダル面（cc-modal）の小サイズに、共通の共有ダイアログ本体（cc-share-modal）を載せる。
// Small shared modal surface (cc-modal) carrying the shared share-dialog body (cc-share-modal).
export function MemoShareModal() {
  const {
    isShareModalOpen,
    closeShareModal,
    shareUrl,
    shareStatus,
    copyShareLink,
    openNativeShareSheet,
    shareLoading,
    supportsNativeShare,
    shareSnsLinks,
  } = useMemoPageModalsContext();
  const { t } = useTranslation();
  return (
    <ModalShell
      isOpen={isShareModalOpen}
      onClose={closeShareModal}
      id="memo-share-modal"
      className="cc-modal cc-share-modal memo-modal-scope memo-share-modal"
      labelledBy="memoShareTitle"
      initialFocusSelector="#memo-share-copy-btn"
    >
      <div className="cc-modal__panel cc-modal__panel--sm cc-share-modal__content" tabIndex={-1}>
        <header className="cc-modal__header cc-share-modal__header">
          <div className="cc-modal__heading">
            <h2 className="cc-modal__title" id="memoShareTitle">{t("memo.share")}</h2>
            <p className="cc-modal__lead cc-share-modal__lead">{t("memo.shareDescription")}</p>
          </div>
          <ModalCloseButton label={t("memo.closeShare")} onClick={closeShareModal} />
        </header>

        <div className="cc-modal__body">
          <ShareDialogContent
            shareUrl={shareUrl}
            shareLoading={shareLoading}
            shareStatus={shareStatus ? { text: shareStatus.text, isError: shareStatus.type === "error" } : null}
            shareStatusId="memo-share-status"
            shareStatusClassName="cc-share-modal__status"
            shareStatusErrorClassName="cc-share-modal__status--error"
            linkInputId="memo-share-link-input"
            linkInputAriaLabel={t("memo.share")}
            linkPlaceholder={t("memo.preparingShareLink")}
            copyButtonId="memo-share-copy-btn"
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
    </ModalShell>
  );
}
