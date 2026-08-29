import {
  useCallback,
  useState,
  type ChangeEvent,
  type FormEvent,
  type RefObject
} from "react";

import { showToast } from "../../scripts/core/toast";
import { deriveLegacyPromptType } from "../../scripts/prompt_share/prompt_type_registry";
import type { ContentFormat, MediaType } from "../../scripts/prompt_share/types";
import { settingsFetchJsonOrThrow } from "../../scripts/user/settings/api";
import type { EditPromptFormState } from "../../scripts/user/settings/page_types";
import {
  buildPromptUpdatePayload,
  parsePromptManageMutationResponse
} from "../../scripts/user/settings/types";
import { useTranslation } from "../../contexts/locale_context";
import type { PromptRecord } from "./prompt_card";
import { getPromptId } from "./prompt_share_page_utils";

type UsePromptInlineEditOptions = {
  currentUserId: number | null;
  promptsRef: RefObject<PromptRecord[]>;
  updatePromptRecord: (
    clientId: string,
    updater: (prompt: PromptRecord) => PromptRecord
  ) => void;
};

// 共有フィード上の本人投稿編集を管理し、所有者の再確認後に既存更新APIへ送る。
// Manages owned-post editing in the share feed and rechecks ownership before using the update API.
export function usePromptInlineEdit({
  currentUserId,
  promptsRef,
  updatePromptRecord
}: UsePromptInlineEditOptions) {
  const { t } = useTranslation();
  const [editPromptForm, setEditPromptForm] = useState<EditPromptFormState | null>(null);
  const [isEditSaving, setIsEditSaving] = useState(false);

  const resetEditPrompt = useCallback(() => {
    setEditPromptForm(null);
  }, []);

  const beginEditPrompt = useCallback((prompt: PromptRecord) => {
    const promptId = getPromptId(prompt);
    if (
      !promptId ||
      currentUserId === null ||
      Number(prompt.author_user_id || 0) !== currentUserId
    ) {
      return false;
    }
    const isSkill = prompt.content_format === "skill";
    setEditPromptForm({
      id: promptId,
      title: prompt.title,
      category: prompt.category || "",
      content: isSkill ? prompt.skill_markdown || "" : prompt.content,
      description: prompt.description || "",
      contentFormat: prompt.content_format || "prompt",
      mediaType: prompt.media_type || "text",
      attributes: prompt.attributes || {},
      inputExamples: prompt.input_examples || "",
      outputExamples: prompt.output_examples || ""
    });
    return true;
  }, [currentUserId]);

  const handleEditPromptChange = useCallback(
    (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
      const { name, value } = event.target;
      setEditPromptForm((current) => current ? { ...current, [name]: value } : current);
    },
    []
  );

  const handleEditPromptCategoryChange = useCallback((value: string) => {
    setEditPromptForm((current) => current ? { ...current, category: value } : current);
  }, []);

  const handleEditPromptSubmit = useCallback(async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (
      !editPromptForm ||
      !editPromptForm.id ||
      !editPromptForm.title.trim() ||
      !editPromptForm.content.trim() ||
      isEditSaving
    ) {
      if (!isEditSaving) {
        showToast(t("promptShare.formIncomplete"), { variant: "error" });
      }
      return false;
    }

    const target = promptsRef.current?.find(
      (prompt) => getPromptId(prompt) === editPromptForm.id
    );
    if (
      !target ||
      currentUserId === null ||
      Number(target.author_user_id || 0) !== currentUserId
    ) {
      showToast(t("promptShare.updateFailed"), { variant: "error" });
      return false;
    }

    setIsEditSaving(true);
    try {
      const { payload } = await settingsFetchJsonOrThrow(
        `/prompt_manage/api/prompts/${encodeURIComponent(editPromptForm.id)}`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify(buildPromptUpdatePayload(editPromptForm))
        },
        { defaultMessage: t("promptShare.updateFailed") }
      );
      const response = parsePromptManageMutationResponse(payload);
      const isSkill = editPromptForm.contentFormat === "skill";
      const includeExamples = !isSkill && editPromptForm.mediaType === "text";
      const nextAttributes = isSkill
        ? { ...editPromptForm.attributes, skill_markdown: editPromptForm.content }
        : editPromptForm.attributes;
      updatePromptRecord(target.clientId, (prompt) => ({
        ...prompt,
        title: editPromptForm.title.trim(),
        category: editPromptForm.category,
        content: isSkill ? "" : editPromptForm.content,
        description: editPromptForm.description,
        content_format: editPromptForm.contentFormat,
        media_type: editPromptForm.mediaType,
        attributes: nextAttributes,
        prompt_type: deriveLegacyPromptType(
          editPromptForm.contentFormat as ContentFormat,
          editPromptForm.mediaType as MediaType
        ),
        skill_markdown: isSkill ? editPromptForm.content : prompt.skill_markdown,
        input_examples: includeExamples ? editPromptForm.inputExamples : "",
        output_examples: includeExamples ? editPromptForm.outputExamples : ""
      }));
      showToast(response.message || t("promptShare.updated"), { variant: "success" });
      return true;
    } catch (error) {
      showToast(
        error instanceof Error ? error.message : t("promptShare.updateFailed"),
        { variant: "error" }
      );
      return false;
    } finally {
      setIsEditSaving(false);
    }
  }, [
    currentUserId,
    editPromptForm,
    isEditSaving,
    promptsRef,
    t,
    updatePromptRecord
  ]);

  return {
    beginEditPrompt,
    editPromptForm,
    handleEditPromptCategoryChange,
    handleEditPromptChange,
    handleEditPromptSubmit,
    isEditSaving,
    resetEditPrompt
  };
}
