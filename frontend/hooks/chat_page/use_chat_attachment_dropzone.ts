// チャット入力欄へのファイルのドラッグ＆ドロップによる添付と、ドラッグ中の表示状態を扱う hook。呼び出し元は components/chat_page/chat_main_section.tsx と setup_section.tsx。
// Hook for attaching files to the chat composer by drag and drop, including the drag-over state. Used by components/chat_page/chat_main_section.tsx and setup_section.tsx.
import { useCallback, useRef, useState, type Dispatch, type DragEvent, type SetStateAction } from "react";

import {
  MAX_ATTACHED_FILES,
  mergeChatAttachments,
  readSelectedChatAttachments,
} from "../../lib/chat_page/file_attachments";
import type { AttachedFile } from "../../lib/chat_page/types";
import { useTranslation } from "../../contexts/locale_context";

type FocusTargetRef = {
  current: { focus: () => void } | null;
};

type ChatAttachmentDropzoneOptions = {
  attachedFiles: AttachedFile[];
  setAttachedFiles: Dispatch<SetStateAction<AttachedFile[]>>;
  isAttachmentDisabled: boolean;
  /** 画像を読めるモデルを選んでいるか / Whether the selected model reads images */
  allowImages: boolean;
  focusTargetRef: FocusTargetRef;
  notifyAttachmentError: (message: string) => void;
};

// ドラッグされているものにファイルが含まれるか（文字列や要素のドラッグは対象外）
// Whether the drag carries files (text or element drags are ignored)
function eventHasDraggedFiles(event: DragEvent<HTMLElement>) {
  return Array.from(event.dataTransfer.types).includes("Files");
}

export function useChatAttachmentDropzone({
  attachedFiles,
  setAttachedFiles,
  isAttachmentDisabled,
  allowImages,
  focusTargetRef,
  notifyAttachmentError,
}: ChatAttachmentDropzoneOptions) {
  const { locale, t } = useTranslation();
  // 子要素をまたぐたびに dragenter / dragleave が発火するため、出入りの深さを数えて、本当に領域を出たときだけ表示を解除する
  // dragenter / dragleave fire whenever the pointer crosses child elements, so count the depth and clear the highlight only when truly leaving the area
  const attachmentDragDepthRef = useRef(0);
  const [isAttachmentDropActive, setIsAttachmentDropActive] = useState(false);
  // 添付が無効でなく、上限（MAX_ATTACHED_FILES）にも達していないときだけ、ドロップを受け付ける
  // Accept drops only when attachments are enabled and the MAX_ATTACHED_FILES limit is not reached
  const canAttachMoreFiles = !isAttachmentDisabled && attachedFiles.length < MAX_ATTACHED_FILES;

  const resetAttachmentDragState = useCallback(() => {
    attachmentDragDepthRef.current = 0;
    setIsAttachmentDropActive(false);
  }, []);

  // 選択・貼り付け・ドロップされたファイルを検証して添付に加える。isCurrent は、読み込み中に画面やルームが変わったときに結果を捨てるための判定
  // Validate selected / pasted / dropped files and add them as attachments; isCurrent lets a result be discarded if the screen or room changed while reading
  const attachSelectedFiles = useCallback(
    async (files: File[], isCurrent: () => boolean = () => true) => {
      if (files.length === 0 || !isCurrent()) return;

      if (isAttachmentDisabled) {
        notifyAttachmentError(t("chat.attachmentUnavailable"));
        return;
      }

      if (attachedFiles.length >= MAX_ATTACHED_FILES) {
        notifyAttachmentError(locale === "en" ? `You can attach up to ${MAX_ATTACHED_FILES} files.` : `添付できるファイルは${MAX_ATTACHED_FILES}件までです。`);
        return;
      }

      const selectedFiles = await readSelectedChatAttachments(files, attachedFiles, (message) => {
        if (isCurrent()) notifyAttachmentError(message);
      }, { allowImages });
      if (selectedFiles.length === 0 || !isCurrent()) return;
      setAttachedFiles((prev) => mergeChatAttachments(prev, selectedFiles));
      focusTargetRef.current?.focus();
    },
    [allowImages, attachedFiles, focusTargetRef, isAttachmentDisabled, locale, notifyAttachmentError, setAttachedFiles, t],
  );

  const handleAttachmentDragEnter = useCallback(
    (event: DragEvent<HTMLElement>) => {
      if (!eventHasDraggedFiles(event)) return;
      event.preventDefault();
      event.stopPropagation();
      event.dataTransfer.dropEffect = canAttachMoreFiles ? "copy" : "none";
      attachmentDragDepthRef.current += 1;
      setIsAttachmentDropActive(canAttachMoreFiles);
    },
    [canAttachMoreFiles],
  );

  const handleAttachmentDragOver = useCallback(
    (event: DragEvent<HTMLElement>) => {
      if (!eventHasDraggedFiles(event)) return;
      event.preventDefault();
      event.stopPropagation();
      event.dataTransfer.dropEffect = canAttachMoreFiles ? "copy" : "none";
    },
    [canAttachMoreFiles],
  );

  const handleAttachmentDragLeave = useCallback((event: DragEvent<HTMLElement>) => {
    if (!eventHasDraggedFiles(event)) return;
    event.preventDefault();
    event.stopPropagation();
    attachmentDragDepthRef.current = Math.max(0, attachmentDragDepthRef.current - 1);
    if (attachmentDragDepthRef.current === 0) {
      setIsAttachmentDropActive(false);
    }
  }, []);

  const handleAttachmentDrop = useCallback(
    (event: DragEvent<HTMLElement>) => {
      if (!eventHasDraggedFiles(event)) return;
      event.preventDefault();
      event.stopPropagation();
      resetAttachmentDragState();
      attachSelectedFiles(Array.from(event.dataTransfer.files));
    },
    [attachSelectedFiles, resetAttachmentDragState],
  );

  return {
    attachSelectedFiles,
    isAttachmentDropActive,
    attachmentDropzoneProps: {
      onDragEnter: handleAttachmentDragEnter,
      onDragOver: handleAttachmentDragOver,
      onDragLeave: handleAttachmentDragLeave,
      onDrop: handleAttachmentDrop,
    },
  };
}
