import { memo } from "react";

import { useTranslation } from "../../../contexts/locale_context";
import type { MessageKey } from "../../../lib/i18n/catalogs/ja";
import type { ToolApprovalApi } from "../../../types/generated/api_schemas";
import { ExpandableText, PreviewField, PreviewText } from "./shared";

type AnyPreview = NonNullable<ToolApprovalApi["preview"]>;
type PromptsPreview = Extract<AnyPreview, { kind: "publish_prompt" | "public_prompt_edit" | "my_prompt_save" | "my_skill_save" }>;
type MyPromptPreview = Extract<PromptsPreview, { kind: "my_prompt_save" }>;
type ClearedField = NonNullable<MyPromptPreview["clear_fields"]>[number];

const CLEAR_FIELD_KEYS: Record<ClearedField, MessageKey> = {
  response_rules: "chat.toolApproval.preview.responseRules",
  output_skeleton: "chat.toolApproval.preview.outputSkeleton",
  input_examples: "chat.toolApproval.preview.inputExamples",
  output_examples: "chat.toolApproval.preview.outputExamples",
};

function PrivateOverlapExcerpts({ excerpts }: { excerpts: string[] }) {
  const { t } = useTranslation();
  if (excerpts.length === 0) return null;

  return (
    <PreviewField
      label={t("chat.toolApproval.preview.privateOverlapExcerpt")}
      className="tool-approval-preview__field--warning"
    >
      <ul className="tool-approval-preview__overlap-list">
        {excerpts.map((excerpt, index) => (
          <li key={index}>
            <PreviewText text={excerpt} excerpt />
          </li>
        ))}
      </ul>
    </PreviewField>
  );
}

// 公開プロンプトの投稿・編集、自分用プロンプト（Task）・個人Skillの作成/編集案を、実行前に確かめられる
// 形で見せる。非公開内容の混入が見つかった場合は、一致した箇所を専用の警告欄に出す
// （カードの本体の警告リストは tool_approval_card.tsx が描く）。
// Shows public prompt publishing/editing and personal prompt/Skill proposals so they can be checked
// before running. When private content overlaps, matching passages appear here; the card's warning
// banner is drawn by tool_approval_card.tsx.
function PromptsApprovalPreviewComponent({ preview }: { preview: PromptsPreview }) {
  const { t } = useTranslation();
  const untitled = t("chat.toolApproval.preview.untitled");

  if (preview.kind === "publish_prompt") {
    const excerpts = preview.private_overlap_excerpts ?? [];
    return (
      <dl className="tool-approval-preview">
        <PreviewField label={t("chat.toolApproval.preview.title")}>{preview.title.trim() || untitled}</PreviewField>
        {preview.category ? (
          <PreviewField label={t("chat.toolApproval.preview.category")}>{preview.category}</PreviewField>
        ) : null}
        {preview.description ? (
          <PreviewField label={t("chat.toolApproval.preview.description")}>
            <ExpandableText text={preview.description} />
          </PreviewField>
        ) : null}
        <PreviewField label={t("chat.toolApproval.preview.content")}>
          <ExpandableText text={preview.content} />
        </PreviewField>
        {preview.input_examples ? (
          <PreviewField label={t("chat.toolApproval.preview.inputExamples")}>
            <ExpandableText text={preview.input_examples} />
          </PreviewField>
        ) : null}
        {preview.output_examples ? (
          <PreviewField label={t("chat.toolApproval.preview.outputExamples")}>
            <ExpandableText text={preview.output_examples} />
          </PreviewField>
        ) : null}
        {preview.ai_model ? (
          <PreviewField label={t("chat.toolApproval.preview.aiModel")}>{preview.ai_model}</PreviewField>
        ) : null}
        <PrivateOverlapExcerpts excerpts={excerpts} />
      </dl>
    );
  }

  if (preview.kind === "public_prompt_edit") {
    return (
      <dl className="tool-approval-preview">
        <PreviewField label={t("chat.toolApproval.preview.beforeTitle")}>
          {preview.before_title.trim() || untitled}
        </PreviewField>
        <PreviewField label={t("chat.toolApproval.preview.afterTitle")}>
          {preview.title.trim() || untitled}
        </PreviewField>
        <PreviewField label={t("chat.toolApproval.preview.beforeContent")}>
          <ExpandableText text={preview.before_content} />
        </PreviewField>
        <PreviewField label={t("chat.toolApproval.preview.afterContent")}>
          <ExpandableText text={preview.content} />
        </PreviewField>
        <PrivateOverlapExcerpts excerpts={preview.private_overlap_excerpts ?? []} />
      </dl>
    );
  }

  if (preview.kind === "my_prompt_save") {
    const clearFields = preview.clear_fields ?? [];
    return (
      <dl className="tool-approval-preview">
        <PreviewField label={t("chat.toolApproval.preview.targetPrompt")}>
          {preview.task_id === null
            ? t("chat.toolApproval.preview.newPrompt")
            : `${preview.current_title?.trim() || untitled} (#${preview.task_id})`}
        </PreviewField>
        <PreviewField label={t("chat.toolApproval.preview.title")}>{preview.title.trim() || untitled}</PreviewField>
        <PreviewField label={t("chat.toolApproval.preview.promptContent")}>
          <ExpandableText text={preview.prompt_content} />
        </PreviewField>
        {preview.response_rules ? (
          <PreviewField label={t("chat.toolApproval.preview.responseRules")}>
            <ExpandableText text={preview.response_rules} />
          </PreviewField>
        ) : null}
        {preview.output_skeleton ? (
          <PreviewField label={t("chat.toolApproval.preview.outputSkeleton")}>
            <ExpandableText text={preview.output_skeleton} />
          </PreviewField>
        ) : null}
        {preview.input_examples ? (
          <PreviewField label={t("chat.toolApproval.preview.inputExamples")}>
            <ExpandableText text={preview.input_examples} />
          </PreviewField>
        ) : null}
        {preview.output_examples ? (
          <PreviewField label={t("chat.toolApproval.preview.outputExamples")}>
            <ExpandableText text={preview.output_examples} />
          </PreviewField>
        ) : null}
        {clearFields.length > 0 ? (
          <PreviewField label={t("chat.toolApproval.preview.clearedFields")}>
            {clearFields.map((field) => t(CLEAR_FIELD_KEYS[field])).join(", ")}
          </PreviewField>
        ) : null}
      </dl>
    );
  }

  return (
    <dl className="tool-approval-preview">
      <PreviewField label={t("chat.toolApproval.preview.targetSkill")}>
        {preview.skill_id === null
          ? t("chat.toolApproval.preview.newSkill")
          : preview.current_name?.trim() || preview.name?.trim() || untitled}
      </PreviewField>
      {preview.name !== null ? (
        <PreviewField label={t("chat.toolApproval.preview.skillName")}>{preview.name.trim() || untitled}</PreviewField>
      ) : null}
      {preview.instructions !== null ? (
        <PreviewField label={t("chat.toolApproval.preview.skillInstructions")}>
          <ExpandableText text={preview.instructions} />
        </PreviewField>
      ) : null}
    </dl>
  );
}

// 不要な再レンダリングを防ぐためにメモ化する
// Memoized to prevent unnecessary re-renders
export const PromptsApprovalPreview = memo(PromptsApprovalPreviewComponent);
PromptsApprovalPreview.displayName = "PromptsApprovalPreview";
