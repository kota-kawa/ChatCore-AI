import { useCallback, useRef, useState, type Dispatch, type DragEvent, type SetStateAction } from "react";

import {
  MAX_ATTACHED_FILES,
  mergeChatAttachments,
  readSelectedChatAttachments,
} from "../../lib/chat_page/file_attachments";
import type { AttachedFile } from "../../lib/chat_page/types";

type FocusTargetRef = {
  current: { focus: () => void } | null;
};

type ChatAttachmentDropzoneOptions = {
  attachedFiles: AttachedFile[];
  setAttachedFiles: Dispatch<SetStateAction<AttachedFile[]>>;
  isAttachmentDisabled: boolean;
  focusTargetRef: FocusTargetRef;
  notifyAttachmentError: (message: string) => void;
};

function eventHasDraggedFiles(event: DragEvent<HTMLElement>) {
  return Array.from(event.dataTransfer.types).includes("Files");
}

export function useChatAttachmentDropzone({
  attachedFiles,
  setAttachedFiles,
  isAttachmentDisabled,
  focusTargetRef,
  notifyAttachmentError,
}: ChatAttachmentDropzoneOptions) {
  const attachmentDragDepthRef = useRef(0);
  const [isAttachmentDropActive, setIsAttachmentDropActive] = useState(false);
  const canAttachMoreFiles = !isAttachmentDisabled && attachedFiles.length < MAX_ATTACHED_FILES;

  const resetAttachmentDragState = useCallback(() => {
    attachmentDragDepthRef.current = 0;
    setIsAttachmentDropActive(false);
  }, []);

  const attachSelectedFiles = useCallback(
    (files: File[]) => {
      if (files.length === 0) return;

      if (isAttachmentDisabled) {
        notifyAttachmentError("チャットの準備中はファイルを添付できません。");
        return;
      }

      if (attachedFiles.length >= MAX_ATTACHED_FILES) {
        notifyAttachmentError(`添付できるファイルは${MAX_ATTACHED_FILES}件までです。`);
        return;
      }

      void readSelectedChatAttachments(files, attachedFiles, notifyAttachmentError).then((selectedFiles) => {
        if (selectedFiles.length === 0) return;
        setAttachedFiles((prev) => mergeChatAttachments(prev, selectedFiles));
        focusTargetRef.current?.focus();
      });
    },
    [attachedFiles, focusTargetRef, isAttachmentDisabled, notifyAttachmentError, setAttachedFiles],
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
