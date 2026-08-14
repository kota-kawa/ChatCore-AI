import React, { useEffect, useRef, useState } from "react";

import { useTranslation } from "../../contexts/locale_context";

type PromptShareDetailImageProps = {
  imageUrl: string;
  title: string;
  // 見出しは描画せず、スクリーンリーダー向けの領域名としてのみ使う
  // Not rendered as a heading; used only as the accessible name of the region
  mediaLabel: string;
};

// 詳細モーダルの作例画像。既定で大きく表示し、クリックでシート全面の拡大表示へ切り替える
// The detail modal's example image: large by default, and expandable to a sheet-wide viewer on click
export function PromptShareDetailImage({
  imageUrl,
  title,
  mediaLabel
}: PromptShareDetailImageProps) {
  const { t } = useTranslation();
  const [isExpanded, setIsExpanded] = useState(false);
  const expandButtonRef = useRef<HTMLButtonElement | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  // 拡大を閉じた直後だけ元のボタンへフォーカスを戻す（初回描画では戻さない）
  // Restore focus to the trigger only right after collapsing, not on the first render
  const wasExpandedRef = useRef(false);
  const altText = t("promptShare.exampleImageAlt", { title });

  // 別のプロンプトへ切り替わったら拡大表示は必ず畳む
  // Always collapse the viewer when the modal moves on to another prompt
  useEffect(() => {
    setIsExpanded(false);
  }, [imageUrl]);

  useEffect(() => {
    if (isExpanded) {
      // 拡大直後に閉じるボタンへフォーカスを移し、Escape/Tabを拡大表示側で受け取れるようにする
      // Focus the close button so the viewer, not the modal, receives Escape and Tab
      closeButtonRef.current?.focus();
    } else if (wasExpandedRef.current) {
      expandButtonRef.current?.focus();
    }
    wasExpandedRef.current = isExpanded;
  }, [isExpanded]);

  // 拡大表示中のキー操作はここで完結させる。preventDefaultすることで
  // 詳細モーダル側のEscape処理（モーダルごと閉じる）へは伝えない
  // Keyboard handling stays inside the viewer; preventDefault stops the detail modal's
  // Escape handler from closing the whole modal underneath
  const handleViewerKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      setIsExpanded(false);
      return;
    }
    if (event.key === "Tab") {
      event.preventDefault();
      closeButtonRef.current?.focus();
    }
  };

  // 見出しと補足文は画像を見れば分かる情報なので描画せず、領域名としてのラベルはaria-labelにだけ残す
  // The heading and helper text just restate what the image shows, so only the accessible region name remains
  return (
    <aside id="modalReferenceImageGroup" className="prompt-detail-media" aria-label={mediaLabel}>
      {/* 画像そのものを拡大トリガーにする。枠は画像の実寸比に追従させ、余白で埋めない
          The image itself is the trigger; the frame follows the image ratio instead of letterboxing */}
      <button
        type="button"
        className="modal-reference-image"
        ref={expandButtonRef}
        onClick={() => {
          setIsExpanded(true);
        }}
        aria-label={t("promptShare.expandImage")}
      >
        <img id="modalReferenceImage" src={imageUrl} alt={altText} />
        <span className="modal-reference-image__zoom" aria-hidden="true">
          <i className="bi bi-arrows-fullscreen"></i>
        </span>
      </button>

      {isExpanded ? (
        <div
          className="prompt-detail-image-viewer"
          role="dialog"
          aria-modal="true"
          aria-label={altText}
          onKeyDown={handleViewerKeyDown}
          onClick={(event) => {
            // 画像の外側（背景）クリックで閉じる / clicking the backdrop closes the viewer
            if (event.target === event.currentTarget) {
              setIsExpanded(false);
            }
          }}
        >
          <img className="prompt-detail-image-viewer__image" src={imageUrl} alt={altText} />
          <button
            type="button"
            className="prompt-detail-image-viewer__close"
            ref={closeButtonRef}
            aria-label={t("promptShare.closeExpandedImage")}
            onClick={() => {
              setIsExpanded(false);
            }}
          >
            <i className="bi bi-x-lg" aria-hidden="true"></i>
          </button>
        </div>
      ) : null}
    </aside>
  );
}
