import { useCallback, useEffect, useRef, useState, type ChangeEvent } from "react";

import { showToast } from "../../scripts/core/toast";
import {
  mediaAllowsAttachment,
  validateAttachmentFile
} from "../../scripts/prompt_share/prompt_type_registry";
import type { MediaType } from "../../scripts/prompt_share/types";

// 投稿フォームの添付ファイル選択、プレビューURL、検証、解放処理をまとめて管理する
// Manages composer attachment selection, preview URL, validation, and cleanup
export function usePromptImageSelection(mediaType: MediaType) {
  const [referenceImageFile, setReferenceImageFile] = useState<File | null>(null);
  const [promptImagePreviewUrl, setPromptImagePreviewUrl] = useState("");
  const [promptImagePreviewName, setPromptImagePreviewName] = useState("");

  const promptImageInputRef = useRef<HTMLInputElement | null>(null);
  const promptImagePreviewUrlRef = useRef("");

  // 選択中メディアの添付ルール（拡張子・MIME・サイズ）でファイルを検証する。
  // Validate the file against the active media's attachment rule (ext / MIME / size).
  const validateReferenceImageFile = useCallback(
    (file: File | null) => validateAttachmentFile(mediaType, file),
    [mediaType]
  );

  // 画像プレビューのObject URLを解放してメモリリークを防ぐ
  // Revokes the image preview Object URL to prevent memory leaks
  const revokePromptImagePreview = useCallback(() => {
    if (!promptImagePreviewUrlRef.current) {
      return;
    }
    URL.revokeObjectURL(promptImagePreviewUrlRef.current);
    promptImagePreviewUrlRef.current = "";
  }, []);

  // 選択中の画像ファイルとプレビューを全て削除し、inputの値もリセットする
  // Removes the selected image file, clears the preview, and resets the file input value
  const clearPromptImageSelection = useCallback(() => {
    revokePromptImagePreview();
    setReferenceImageFile(null);
    setPromptImagePreviewUrl("");
    setPromptImagePreviewName("");
    if (promptImageInputRef.current) {
      promptImageInputRef.current.value = "";
    }
  }, [revokePromptImagePreview]);

  // 新しいファイルが選択された際に以前のObject URLを解放してから新しいプレビューを生成する
  // Revokes the previous Object URL before generating a new preview to avoid accumulating blob URLs
  const updatePromptImagePreview = useCallback(
    (file: File | null) => {
      if (!file) {
        clearPromptImageSelection();
        return;
      }
      revokePromptImagePreview();
      const nextUrl = URL.createObjectURL(file);
      promptImagePreviewUrlRef.current = nextUrl;
      setReferenceImageFile(file);
      setPromptImagePreviewUrl(nextUrl);
      setPromptImagePreviewName(`${file.name} (${Math.max(1, Math.round(file.size / 1024))}KB)`);
    },
    [clearPromptImageSelection, revokePromptImagePreview]
  );

  // 画像ファイルが選択されたときにバリデーションを行い、問題なければプレビューを更新する
  // Validates the selected image file on change and updates the preview if validation passes
  const handleReferenceImageChange = useCallback(
    (event: ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0] || null;
      const validationError = validateReferenceImageFile(file);
      if (validationError) {
        showToast(validationError, { variant: "error" });
        clearPromptImageSelection();
        return;
      }
      updatePromptImagePreview(file);
    },
    [clearPromptImageSelection, updatePromptImagePreview, validateReferenceImageFile]
  );

  // 添付非対応のメディアへ切り替えた場合は添付の選択をクリアしてメモリを解放する
  // Clears the attachment selection to free memory when switching to a media that disallows attachments
  useEffect(() => {
    if (!mediaAllowsAttachment(mediaType)) {
      clearPromptImageSelection();
    }
  }, [clearPromptImageSelection, mediaType]);

  useEffect(() => {
    return () => {
      revokePromptImagePreview();
    };
  }, [revokePromptImagePreview]);

  return {
    clearPromptImageSelection,
    handleReferenceImageChange,
    promptImageInputRef,
    promptImagePreviewName,
    promptImagePreviewUrl,
    referenceImageFile,
    validateReferenceImageFile
  };
}
